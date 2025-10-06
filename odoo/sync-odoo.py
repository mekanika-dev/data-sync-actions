#!/usr/bin/env python3
"""
Odoo BOM Recursive Fetcher
Fetches Bill of Materials data recursively from Odoo ERP and exports to CSV
"""

import xmlrpc.client
import csv
import argparse
import os
import sys
from datetime import datetime
from typing import List, Dict, Set, Optional, Tuple


class OdooBOMFetcher:
    def __init__(self, url: str, db: str, username: str, api_key: str):
        """
        Initialize connection to Odoo instance

        Args:
            url: Odoo instance URL (e.g., 'https://your-odoo.com')
            db: Database name
            username: Odoo username
            api_key: Odoo API key for authentication
        """
        self.url = url
        self.db = db
        self.username = username
        self.api_key = api_key
        self.password = api_key  # API key is used as password in XML-RPC

        # Setup XML-RPC endpoints
        self.common = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/common')
        self.models = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/object')

        # Authenticate using API key
        self.uid = self.common.authenticate(db, username, api_key, {})

        if not self.uid:
            raise Exception("Authentication failed. Please check your API key.")

        print(f"Connected to Odoo (User ID: {self.uid})")
        
        # Cache for already processed BOMs to avoid circular references
        self.processed_boms: Set[int] = set()
        self.bom_data: List[Dict] = []
        # Cache for parent BOM names
        self.parent_names: Dict[str, str] = {}

        # Keywords to filter out packaging/labeling components
        # Using more specific terms to avoid filtering actual components
        self.filter_keywords = [
            'zebra', 'label', 'plastic bag', 'zip bag',
            'adhesive foam', 'bubble wrap', 'sleeve',
            'sticker', 'certificate', 'user manual', 'equipment wire',
            'pallet', 'cardboard', 'packaging', 'box'
        ]
    
    def search_read(self, model: str, domain: List, fields: List) -> List[Dict]:
        """Helper method to perform search_read operations"""
        return self.models.execute_kw(
            self.db, self.uid, self.password,
            model, 'search_read',
            [domain],
            {'fields': fields}
        )
    
    def get_product_by_reference(self, reference: str) -> Optional[Dict]:
        """
        Find product by internal reference
        
        Args:
            reference: Product internal reference (default_code)
            
        Returns:
            Product data dict or None if not found
        """
        products = self.search_read(
            'product.product',
            [['default_code', '=', reference]],
            ['id', 'name', 'default_code']
        )
        
        if not products:
            # Try with product.template as fallback
            templates = self.search_read(
                'product.template',
                [['default_code', '=', reference]],
                ['id', 'name', 'default_code', 'product_variant_ids']
            )
            if templates and templates[0]['product_variant_ids']:
                # Get the first variant
                products = self.search_read(
                    'product.product',
                    [['id', '=', templates[0]['product_variant_ids'][0]]],
                    ['id', 'name', 'default_code']
                )
        
        return products[0] if products else None
    
    def get_bom_for_product(self, product_id: int) -> Optional[Dict]:
        """
        Get the main BOM for a product
        
        Args:
            product_id: Product ID
            
        Returns:
            BOM data dict or None if no BOM exists
        """
        boms = self.search_read(
            'mrp.bom',
            [
                ['product_id', '=', product_id],
                ['active', '=', True]
            ],
            ['id', 'code', 'product_id', 'product_tmpl_id']
        )
        
        if not boms:
            # Try searching by product template
            product = self.search_read(
                'product.product',
                [['id', '=', product_id]],
                ['product_tmpl_id']
            )
            if product:
                tmpl_id = product[0]['product_tmpl_id'][0] if product[0]['product_tmpl_id'] else None
                if tmpl_id:
                    boms = self.search_read(
                        'mrp.bom',
                        [
                            ['product_tmpl_id', '=', tmpl_id],
                            ['active', '=', True],
                            '|',
                            ['product_id', '=', False],
                            ['product_id', '=', product_id]
                        ],
                        ['id', 'code', 'product_id', 'product_tmpl_id']
                    )
        
        return boms[0] if boms else None
    
    def adjust_quantity(self, quantity: float) -> float:
        """
        Adjust quantity based on rules:
        - 11 to 50: subtract 2
        - 50 to 100: subtract 4
        - above 100: subtract 10
        """
        if quantity >= 11 and quantity < 50:
            return max(0, quantity - 2)
        elif quantity >= 50 and quantity < 100:
            return max(0, quantity - 4)
        elif quantity >= 100:
            return max(0, quantity - 10)
        return quantity

    def get_collapsed_single_child(self, bom_id: int, parent_qty: float, level: int) -> Optional[Dict]:
        """
        Recursively check if a BOM has only one non-filtered child and return the final component.

        Args:
            bom_id: BOM ID to check
            parent_qty: Quantity multiplier from parent
            level: Current level for the final component

        Returns:
            Dict with component data if BOM should be collapsed, None otherwise
        """
        # Get BOM lines
        bom_lines = self.search_read(
            'mrp.bom.line',
            [['bom_id', '=', bom_id]],
            ['product_id', 'product_qty', 'product_uom_id']
        )

        # Filter out invalid lines and get non-filtered components
        valid_components = []
        for line in bom_lines:
            if not line['product_id']:
                continue

            product_id = line['product_id'][0]
            quantity = line['product_qty'] * parent_qty

            # Get product details
            product_details = self.search_read(
                'product.product',
                [['id', '=', product_id]],
                ['default_code', 'name', 'display_name', 'product_tmpl_id']
            )

            if not product_details:
                continue

            # Get template name for cleaner naming
            template_name = None
            if product_details[0].get('product_tmpl_id'):
                template_id = product_details[0]['product_tmpl_id'][0] if isinstance(product_details[0]['product_tmpl_id'], (list, tuple)) else product_details[0]['product_tmpl_id']
                template_details = self.search_read(
                    'product.template',
                    [['id', '=', template_id]],
                    ['name']
                )
                if template_details:
                    template_name = template_details[0]['name']

            # Determine final name
            if template_name and template_name != product_details[0]['name']:
                final_name = template_name
            else:
                final_name = product_details[0]['name']

            # Remove (copy) suffix
            if final_name.endswith(' (copy)'):
                final_name = final_name[:-7]

            component_ref = product_details[0]['default_code'] or ""

            # Check if component should be filtered out
            should_filter = any(keyword in final_name.lower() for keyword in self.filter_keywords)
            if not should_filter:
                valid_components.append({
                    'product_id': product_id,
                    'component_reference': component_ref,
                    'component_name': final_name,
                    'quantity': quantity,
                    'level': level
                })

        # If there's exactly one valid component, check if it should be collapsed further
        if len(valid_components) == 1:
            component = valid_components[0]

            # Check if this component has its own BOM
            child_bom = self.get_bom_for_product(component['product_id'])
            if child_bom:
                # Recursively check if the child BOM should also be collapsed
                collapsed_child = self.get_collapsed_single_child(child_bom['id'], component['quantity'], level + 1)
                if collapsed_child:
                    return collapsed_child
                else:
                    # Child BOM has multiple components, so we keep this component but mark it as having a BOM
                    component['has_child_bom'] = True
                    return component
            else:
                # No child BOM, this is a leaf component
                component['has_child_bom'] = False
                return component

        # Multiple components or no valid components - don't collapse
        return None

    def get_bom_lines(self, bom_id: int, parent_reference: str, parent_qty: float = 1.0, level: int = 1) -> None:
        """
        Recursively fetch BOM lines

        Args:
            bom_id: BOM ID to fetch lines from
            parent_reference: Parent product reference for tracking hierarchy
            parent_qty: Quantity multiplier from parent
            level: Current depth level in the BOM hierarchy (0 = main product)
        """
        if bom_id in self.processed_boms:
            print(f"  Warning: Circular reference detected for BOM ID {bom_id}, skipping...")
            return
        
        self.processed_boms.add(bom_id)
        
        # Get BOM lines
        bom_lines = self.search_read(
            'mrp.bom.line',
            [['bom_id', '=', bom_id]],
            ['product_id', 'product_qty', 'product_uom_id']
        )
        
        print(f"  -> Found {len(bom_lines)} components in BOM")
        
        for line in bom_lines:
            if not line['product_id']:
                continue

            product_id = line['product_id'][0]
            quantity = line['product_qty'] * parent_qty

            # Get full product details - try multiple approaches to get correct name
            product_details = self.search_read(
                'product.product',
                [['id', '=', product_id]],
                ['default_code', 'name', 'display_name', 'product_tmpl_id']
            )

            # Debug specific product to understand naming
            component_ref_temp = product_details[0]['default_code'] if product_details else ""
            if component_ref_temp == "M00279":
                print(f"      [DEBUG M00279] Product name: '{product_details[0]['name']}'")
                print(f"      [DEBUG M00279] Display name: '{product_details[0]['display_name']}'")

            # Also get template details to compare names
            template_name = None
            if product_details and product_details[0].get('product_tmpl_id'):
                template_id = product_details[0]['product_tmpl_id'][0] if isinstance(product_details[0]['product_tmpl_id'], (list, tuple)) else product_details[0]['product_tmpl_id']
                template_details = self.search_read(
                    'product.template',
                    [['id', '=', template_id]],
                    ['name']
                )
                if template_details:
                    template_name = template_details[0]['name']

            # Try to get the most accurate name
            # Priority: template name (if different and cleaner), then product name, then display name
            if template_name and template_name != product_details[0]['name']:
                # Use template name if it's different (usually more accurate)
                final_name = template_name
            else:
                # Use the product name
                final_name = product_details[0]['name']

            if product_details:
                # Use blank string if no reference instead of PROD_ID
                component_ref = product_details[0]['default_code'] or ""
                # Use the final determined name
                component_name = final_name

                # Remove any ' (copy)' suffix that might be in the name
                if component_name.endswith(' (copy)'):
                    component_name = component_name[:-7]

                print(f"    * {component_ref}: {component_name} (Qty: {quantity})")

                # Check if component should be filtered out
                should_filter = any(keyword in component_name.lower() for keyword in self.filter_keywords)

                if should_filter:
                    print(f"        [Filtered out: packaging/labeling component]")
                else:
                    # Apply quantity adjustment
                    adjusted_qty = self.adjust_quantity(quantity)
                    if quantity != adjusted_qty:
                        print(f"        [Quantity adjusted from {quantity:.2f} to {adjusted_qty:.2f}]")

                    # Get parent name if not cached
                    if parent_reference not in self.parent_names:
                        # Search for parent product to get its name
                        parent_products = self.search_read(
                            'product.product',
                            [['default_code', '=', parent_reference]],
                            ['name', 'product_tmpl_id']
                        )
                        if parent_products:
                            parent_name = parent_products[0]['name']
                            # Try to get cleaner name from template
                            if parent_products[0].get('product_tmpl_id'):
                                template_id = parent_products[0]['product_tmpl_id'][0] if isinstance(parent_products[0]['product_tmpl_id'], (list, tuple)) else parent_products[0]['product_tmpl_id']
                                template_details = self.search_read(
                                    'product.template',
                                    [['id', '=', template_id]],
                                    ['name']
                                )
                                if template_details:
                                    parent_name = template_details[0]['name']
                            # Remove (copy) suffix if present
                            if parent_name.endswith(' (copy)'):
                                parent_name = parent_name[:-7]
                            self.parent_names[parent_reference] = parent_name
                        else:
                            self.parent_names[parent_reference] = parent_reference

                    # Add component to data (including those with child BOMs)
                    self.bom_data.append({
                        'level': level,
                        'component_reference': component_ref,
                        'component_name': component_name,
                        'component_quantity': f"{adjusted_qty:.2f}",
                        'parent_bom_reference': parent_reference,
                        'parent_bom_name': self.parent_names.get(parent_reference, parent_reference),
                        'has_child_bom': False  # Will be updated if child BOM found
                    })

                    # Store index of this item to update has_child_bom if needed
                    item_index = len(self.bom_data) - 1

                # Check if this component has its own BOM
                child_bom = self.get_bom_for_product(product_id)
                if child_bom:
                    # Check if this BOM has only one child and should be collapsed
                    collapsed_component = self.get_collapsed_single_child(child_bom['id'], quantity, level)

                    if collapsed_component:
                        # Remove the parent component we just added and replace with the collapsed child
                        if not should_filter and item_index >= 0:
                            self.bom_data.pop(item_index)

                        # Add the collapsed component directly
                        print(f"      -> Collapsing single-child BOM {component_ref}, showing final component: {collapsed_component['component_reference']}")

                        # Create properly formatted component entry
                        adjusted_qty = self.adjust_quantity(collapsed_component['quantity'])
                        if collapsed_component['quantity'] != adjusted_qty:
                            print(f"        [Quantity adjusted from {collapsed_component['quantity']:.2f} to {adjusted_qty:.2f}]")

                        formatted_component = {
                            'level': collapsed_component['level'],
                            'component_reference': collapsed_component['component_reference'],
                            'component_name': collapsed_component['component_name'],
                            'component_quantity': f"{adjusted_qty:.2f}",
                            'parent_bom_reference': parent_reference,
                            'parent_bom_name': self.parent_names.get(parent_reference, parent_reference),
                            'has_child_bom': collapsed_component.get('has_child_bom', False)
                        }

                        self.bom_data.append(formatted_component)
                    else:
                        # Normal BOM processing - update has_child_bom flag and recurse
                        if not should_filter and item_index >= 0:
                            self.bom_data[item_index]['has_child_bom'] = True
                        print(f"      -> Found child BOM for {component_ref}, fetching recursively...")
                        self.get_bom_lines(child_bom['id'], component_ref if component_ref else component_name, quantity, level + 1)
    
    def fetch_bom_recursive(self, reference: str) -> List[Dict]:
        """
        Main method to fetch BOM data recursively
        
        Args:
            reference: Product internal reference to start from
            
        Returns:
            List of BOM component dictionaries
        """
        print(f"\nSearching for product with reference: {reference}")
        
        # Reset for new fetch
        self.processed_boms.clear()
        self.bom_data.clear()
        
        # Find product
        product = self.get_product_by_reference(reference)
        if not product:
            raise Exception(f"Product with reference '{reference}' not found")
        
        print(f"Found product: {product['name']} (ID: {product['id']})")
        
        # Find BOM
        bom = self.get_bom_for_product(product['id'])
        if not bom:
            raise Exception(f"No active BOM found for product '{reference}'")
        
        print(f"Found BOM (ID: {bom['id']})")
        
        # Cache the main product name
        self.parent_names[reference] = product['name']

        # Add the main product to the BOM data (level 0)
        self.bom_data.append({
            'level': 0,
            'component_reference': reference,
            'component_name': product['name'],
            'component_quantity': "1.00",
            'parent_bom_reference': '',
            'parent_bom_name': '',
            'has_child_bom': True
        })

        # Fetch BOM lines recursively
        print("\nFetching BOM structure recursively...")
        self.get_bom_lines(bom['id'], reference, 1.0, 1)
        
        return self.bom_data
    
    def export_to_csv(self, data: List[Dict], filename: str) -> None:
        """
        Export BOM data to CSV file

        Args:
            data: List of BOM component dictionaries
            filename: Output CSV filename
        """
        if not data:
            print("Warning: No data to export")
            return

        with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
            fieldnames = ['level', 'component_reference', 'component_name', 'component_quantity', 'parent_bom_reference', 'parent_bom_name', 'has_child_bom']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

            writer.writeheader()
            writer.writerows(data)

        print(f"\nExported {len(data)} components to {filename}")


def main():
    parser = argparse.ArgumentParser(
        description='Fetch BOM data recursively from Odoo ERP',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s -r "PROD-001"
  %(prog)s -r "PROD-001" -o custom_output.csv
  %(prog)s -r "PROD-001" --url https://erp.company.com --db prod

Environment variables (optional):
  ODOO_URL      - Odoo instance URL
  ODOO_DB       - Database name
  ODOO_USERNAME - Username
  ODOO_API_KEY  - API key (required if not provided as argument)

Credentials file format (if using --credentials):
  url https://erp.example.com
  db database_name
  username user@example.com
  key api_key_here
        """
    )
    
    parser.add_argument(
        '-r', '--reference',
        required=True,
        help='Product internal reference to fetch BOM for'
    )
    
    parser.add_argument(
        '-o', '--output',
        default=None,
        help='Output CSV filename (default: bom_[reference]_[timestamp].csv)'
    )
    
    parser.add_argument(
        '--url',
        default=os.getenv('ODOO_URL', 'http://localhost:8069'),
        help='Odoo instance URL (default: from ODOO_URL env or http://localhost:8069)'
    )
    
    parser.add_argument(
        '--db',
        default=os.getenv('ODOO_DB', 'odoo'),
        help='Odoo database name (default: from ODOO_DB env or "odoo")'
    )
    
    parser.add_argument(
        '--username',
        default=os.getenv('ODOO_USERNAME', 'admin'),
        help='Odoo username (default: from ODOO_USERNAME env or "admin")'
    )

    parser.add_argument(
        '--api-key',
        default=os.getenv('ODOO_API_KEY'),
        help='Odoo API key for authentication (can be set via ODOO_API_KEY env var)'
    )

    parser.add_argument(
        '--credentials',
        help='Path to credentials file (alternative to individual parameters)'
    )
    
    args = parser.parse_args()

    # Load credentials from file if provided
    if args.credentials:
        if os.path.exists(args.credentials):
            with open(args.credentials, 'r') as f:
                for line in f:
                    parts = line.strip().split(' ', 1)
                    if len(parts) == 2:
                        key, value = parts
                        if key == 'url':
                            args.url = value
                        elif key == 'db':
                            args.db = value
                        elif key == 'username':
                            args.username = value
                        elif key == 'key':
                            args.api_key = value
        else:
            print(f"Error: Credentials file '{args.credentials}' not found", file=sys.stderr)
            return 1

    # Validate required parameters
    if not args.api_key:
        print("Error: API key is required. Set via --api-key, ODOO_API_KEY env var, or --credentials file", file=sys.stderr)
        return 1

    # Generate output filename if not provided
    if not args.output:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        safe_ref = args.reference.replace('/', '_').replace('\\', '_')
        args.output = f"bom_{safe_ref}_{timestamp}.csv"

    try:
        # Initialize fetcher
        fetcher = OdooBOMFetcher(
            url=args.url,
            db=args.db,
            username=args.username,
            api_key=args.api_key
        )
        
        # Fetch BOM data
        bom_data = fetcher.fetch_bom_recursive(args.reference)
        
        # Export to CSV
        fetcher.export_to_csv(bom_data, args.output)
        
        print(f"\nProcess completed successfully!")
        return 0
        
    except Exception as e:
        print(f"\nError: {e}", file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())