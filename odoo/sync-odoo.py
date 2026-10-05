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
        
        # BOMs on the current recursion path, to detect circular references
        self.bom_path: Set[int] = set()
        self.bom_data: List[Dict] = []
        # Cache of product details by product.product ID
        self.product_cache: Dict[int, Optional[Dict]] = {}
        # Cache of attribute ID by product.template.attribute.value ID
        self.ptav_attribute_cache: Dict[int, int] = {}

        # Keywords to filter out packaging/labeling components
        # Using more specific terms to avoid filtering actual components
        self.filter_keywords = [
            'zebra', 'label', 'plastic bag', 'zip bag',
            'adhesive foam', 'bubble wrap', 'sleeve',
            'sticker', 'certificate', 'user manual', 'equipment wire',
            'pallet', 'cardboard', 'packaging', 'tgo', 'bep235', 'bep203', 
            'pcad', 'cad18', 'chad70', 'cpl45', 'vk421', 'poster box', 'u foam', 
            'bor15','bor35'
        ]
    
    def search_read(self, model: str, domain: List, fields: List,
                    order: Optional[str] = None, context: Optional[Dict] = None) -> List[Dict]:
        """Helper method to perform search_read operations with en_GB locale"""
        kwargs = {'fields': fields, 'context': {'lang': 'en_GB', **(context or {})}}
        if order:
            kwargs['order'] = order
        return self.models.execute_kw(
            self.db, self.uid, self.password,
            model, 'search_read',
            [domain],
            kwargs
        )

    def get_product_info(self, product_id: int) -> Optional[Dict]:
        """
        Get cached product details, with the variant name (e.g. "Dust Collection Kit (PRO)")

        Args:
            product_id: Product ID

        Returns:
            Dict with id, reference, name, template_id and ptav_ids, or None if not found
        """
        if product_id not in self.product_cache:
            products = self.search_read(
                'product.product',
                [['id', '=', product_id]],
                ['default_code', 'display_name', 'product_tmpl_id', 'product_template_attribute_value_ids'],
                context={'display_default_code': False, 'active_test': False}
            )
            if products:
                product = products[0]
                self.product_cache[product_id] = {
                    'id': product_id,
                    'reference': product['default_code'] or "",
                    'name': product['display_name'].replace(' (copy)', ''),
                    'template_id': product['product_tmpl_id'][0],
                    'ptav_ids': set(product['product_template_attribute_value_ids']),
                }
            else:
                self.product_cache[product_id] = None
        return self.product_cache[product_id]

    def line_applies_to_variant(self, line_ptav_ids: List[int], variant_ptav_ids: Set[int]) -> bool:
        """
        Check a BOM line's "Apply on Variants" condition, like Odoo's _skip_bom_line:
        for every attribute in the condition, the variant must have one of the listed values.

        Args:
            line_ptav_ids: bom_product_template_attribute_value_ids of the BOM line
            variant_ptav_ids: product_template_attribute_value_ids of the product being exploded

        Returns:
            True if the line applies to the variant
        """
        if not line_ptav_ids:
            return True

        missing = [ptav_id for ptav_id in line_ptav_ids if ptav_id not in self.ptav_attribute_cache]
        if missing:
            for ptav in self.search_read(
                'product.template.attribute.value',
                [['id', 'in', missing]],
                ['attribute_id'],
                context={'active_test': False}
            ):
                self.ptav_attribute_cache[ptav['id']] = ptav['attribute_id'][0]

        required_attributes = {self.ptav_attribute_cache.get(ptav_id) for ptav_id in line_ptav_ids}
        matched_attributes = {self.ptav_attribute_cache.get(ptav_id) for ptav_id in line_ptav_ids
                              if ptav_id in variant_ptav_ids}
        return required_attributes == matched_attributes
    
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
        Get the main BOM for a product, selected like Odoo's _bom_find:
        variant-specific or template BOMs, ordered by sequence, variant-specific first

        Args:
            product_id: Product ID

        Returns:
            BOM data dict or None if no BOM exists
        """
        product = self.get_product_info(product_id)
        if not product:
            return None

        boms = self.search_read(
            'mrp.bom',
            [
                ['active', '=', True],
                '|',
                ['product_id', '=', product_id],
                '&',
                ['product_id', '=', False],
                ['product_tmpl_id', '=', product['template_id']]
            ],
            ['id', 'code', 'product_id', 'product_tmpl_id'],
            order='sequence, product_id, id'
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

    def get_bom_lines(self, bom_id: int, parent: Dict, parent_qty: float = 1.0, level: int = 1) -> None:
        """
        Recursively fetch BOM lines that apply to the parent product variant

        Args:
            bom_id: BOM ID to fetch lines from
            parent: Product info (from get_product_info) of the product this BOM is exploded for
            parent_qty: Quantity multiplier from parent
            level: Current depth level in the BOM hierarchy (0 = main product)
        """
        if bom_id in self.bom_path:
            print(f"  Warning: Circular reference detected for BOM ID {bom_id}, skipping...")
            return

        self.bom_path.add(bom_id)

        parent_reference = parent['reference'] or parent['name']

        # Get BOM lines
        bom_lines = self.search_read(
            'mrp.bom.line',
            [['bom_id', '=', bom_id]],
            ['product_id', 'product_qty', 'product_uom_id', 'bom_product_template_attribute_value_ids']
        )

        print(f"  -> Found {len(bom_lines)} components in BOM")

        for line in bom_lines:
            if not line['product_id']:
                continue

            component = self.get_product_info(line['product_id'][0])
            if not component:
                continue

            component_ref = component['reference']
            component_name = component['name']
            quantity = line['product_qty'] * parent_qty

            if not self.line_applies_to_variant(line['bom_product_template_attribute_value_ids'], parent['ptav_ids']):
                print(f"    - {component_ref}: {component_name} [Skipped: not applicable to variant {parent['name']}]")
                continue

            print(f"    * {component_ref}: {component_name} (Qty: {quantity})")

            # Check if component should be filtered out
            should_filter = any(keyword in component_name.lower() for keyword in self.filter_keywords)
            child_bom = self.get_bom_for_product(component['id'])

            if should_filter:
                print(f"        [Filtered out: packaging/labeling component]")
            else:
                # Apply quantity adjustment
                adjusted_qty = self.adjust_quantity(quantity)
                if quantity != adjusted_qty:
                    print(f"        [Quantity adjusted from {quantity:.2f} to {adjusted_qty:.2f}]")

                # Add component to data (including those with child BOMs)
                self.bom_data.append({
                    'level': level,
                    'component_reference': component_ref,
                    'component_name': component_name,
                    'component_quantity': f"{adjusted_qty:.2f}",
                    'parent_bom_reference': parent_reference,
                    'parent_bom_name': parent['name'],
                    'has_child_bom': bool(child_bom)
                })

            # Recurse into the component's own BOM, exploded for the component variant
            # (Collapsing disabled to show all BOM levels)
            if child_bom:
                print(f"      -> Found child BOM for {component_ref}, fetching recursively...")
                self.get_bom_lines(child_bom['id'], component, quantity, level + 1)

        self.bom_path.discard(bom_id)

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
        self.bom_path.clear()
        self.bom_data.clear()

        # Find product
        found = self.get_product_by_reference(reference)
        product = self.get_product_info(found['id']) if found else None
        if not product:
            raise Exception(f"Product with reference '{reference}' not found")

        print(f"Found product: {product['name']} (ID: {product['id']})")

        # Find BOM
        bom = self.get_bom_for_product(product['id'])
        if not bom:
            raise Exception(f"No active BOM found for product '{reference}'")

        print(f"Found BOM (ID: {bom['id']})")

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
        self.get_bom_lines(bom['id'], product, 1.0, 1)

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