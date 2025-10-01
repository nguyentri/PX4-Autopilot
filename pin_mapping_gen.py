#!/usr/bin/env python3
"""
Pin Mapping Generator for Renesas RA8E1 Microcontroller
Generates pin mapping header file from CSV data
"""

import csv
import re
from collections import defaultdict

# Define PSEL mappings based on current pinmap header
PSEL_MAPPINGS = {
    'AGT': 'PFS_PSEL_AGT',
    'AGTIO': 'PFS_PSEL_AGT',
    'AGTO': 'PFS_PSEL_AGT',
    'AGTOB': 'PFS_PSEL_AGT',
    'AGTOA': 'PFS_PSEL_AGT',
    'AGTEE': 'PFS_PSEL_AGT',
    'GPT': 'PFS_PSEL_GPT',
    'GTIOC': 'PFS_PSEL_GPT',
    'GTETRG': 'PFS_PSEL_GPT',
    'GTADSM': 'PFS_PSEL_GPT',
    'SCI': 'PFS_PSEL_SCI',
    'RXD': 'PFS_PSEL_SCI',
    'TXD': 'PFS_PSEL_SCI',
    'SCK': 'PFS_PSEL_SCI',
    'CTS': 'PFS_PSEL_SCI',
    'DE': 'PFS_PSEL_SCI',
    'SPI': 'PFS_PSEL_SPI',
    'MISO': 'PFS_PSEL_SPI',
    'MOSI': 'PFS_PSEL_SPI',
    'RSPCK': 'PFS_PSEL_SPI',
    'SSL': 'PFS_PSEL_SPI',
    'I2C': 'PFS_PSEL_IIC',
    'SDA': 'PFS_PSEL_IIC',
    'SCL': 'PFS_PSEL_IIC',
    'CAN': 'PFS_PSEL_CAN',
    'CRX': 'PFS_PSEL_CAN',
    'CTX': 'PFS_PSEL_CAN',
    'USB': 'PFS_PSEL_USBFS',
    'ETHERNET': 'PFS_PSEL_ETHERNET',
    'ET0': 'PFS_PSEL_ETHERNET',
    'RMII': 'PFS_PSEL_ETHERNET',
    'REF50CK': 'PFS_PSEL_ETHERNET',
    'SSI': 'PFS_PSEL_SSIE',
    'AUDIO_CLK': 'PFS_PSEL_CLKOUT_ACMPLP_RTC',
    'RTC': 'PFS_PSEL_CLKOUT_ACMPLP_RTC',
    'DAC': 'PFS_PSEL_DAC',
    'DA': 'PFS_PSEL_DAC',
    'OPAMP': 'PFS_PSEL_OPAMP',
    'IVCMP': 'PFS_PSEL_OPAMP',
    'IVREF': 'PFS_PSEL_OPAMP',
    'VCOUT': 'PFS_PSEL_OPAMP',
    'XSPI': 'PFS_PSEL_XSPI',
    'OM': 'PFS_PSEL_XSPI',
    'ULPT': 'PFS_PSEL_ULPT',
    'CEU': 'PFS_PSEL_CEU',
    'VIO': 'PFS_PSEL_CEU',
    'ADTRG': 'PFS_PSEL_CAC_ADC14'
}

def get_psel_value(function_name):
    """Get the appropriate PSEL value for a function"""
    function_upper = function_name.upper()

    # Check for exact matches first
    for key, value in PSEL_MAPPINGS.items():
        if key in function_upper:
            return value

    return None

def clean_function_name(func_name):
    """Clean function name to make it a valid C identifier with proper formatting"""
    # Remove spaces, slashes, and hyphens, replace with underscores
    cleaned = re.sub(r'[-/\s]+', '_', func_name)
    # Remove any remaining invalid characters
    cleaned = re.sub(r'[^A-Za-z0-9_]', '', cleaned)
    return cleaned

def create_function_mapping(func_name):
    """Create proper function mapping for different peripheral types"""
    # Handle SCI functions specially to match the current format
    if '/' in func_name and ('RXD' in func_name or 'TXD' in func_name):
        # For SCI functions like "RXD2_A / MISO2_A / SCL2_A"
        parts = [part.strip() for part in func_name.split('/')]
        if len(parts) >= 3:
            # Extract the common suffix (A, B, C, etc.)
            main_part = parts[0].strip()  # RXD2_A
            if 'RXD' in main_part:
                # Create the combined name: RXD2_MISO2_SCL2_A
                base_num = main_part.split('_')[0][-1]  # Extract number
                suffix = main_part.split('_')[1]       # Extract A/B/C
                func_type = main_part.split('_')[0][:-1]  # Extract RXD
                return f"{func_type}{base_num}_MISO{base_num}_SCL{base_num}_{suffix}"
            elif 'TXD' in main_part:
                # Create the combined name: TXD2_MOSI2_SDA2_A
                base_num = main_part.split('_')[0][-1]  # Extract number
                suffix = main_part.split('_')[1]       # Extract A/B/C
                func_type = main_part.split('_')[0][:-1]  # Extract TXD
                return f"{func_type}{base_num}_MOSI{base_num}_SDA{base_num}_{suffix}"

        # Fallback to first part if parsing fails
        return parts[0].strip().replace(' ', '_')

    # For other functions, use the original cleaning
    return clean_function_name(func_name)

def parse_csv_data():
    """Parse the CSV file and extract pin mapping data"""
    pins_data = {}
    current_port = -1

    # Read CSV data from standard input or file
    csv_file = '/home/a5094159/projects/nuttx_ra_dev/ra8e1_pin_mapping.csv'

    with open(csv_file, 'r') as file:
        csv_reader = csv.reader(file, delimiter='\t')

        for row in csv_reader:
            if len(row) < 2:
                # Handle port section headers
                if len(row) == 1 and row[0].strip().startswith("PORT"):
                    match = re.match(r"PORT (\d+)", row[0].strip())
                    if match:
                        current_port = int(match.group(1))
                continue

            pin_name, functions = row[0].strip(), row[1].strip()

            # Skip header row and port headers
            if pin_name == "Pin" or pin_name.startswith("PORT"):
                continue

            if not pin_name.startswith('P') or not functions:
                continue

            # Extract pin number
            match = re.match(r"P(\d)(\d{2})", pin_name)
            if not match:
                continue

            port_num = int(match.group(1))
            pin_num = int(match.group(2))

            # Parse functions
            func_list = []
            if functions != "(No alternative functions listed)":
                # Split by comma first, then handle complex function names
                for func in functions.split(','):
                    func = func.strip()
                    if func:
                        func_list.append(func)

            pins_data[pin_name] = {
                'port': port_num,
                'pin': pin_num,
                'functions': func_list
            }

    return pins_data

def generate_header():
    """Generate the complete header file"""
    pins_data = parse_csv_data()

    # Collect definitions
    alt_func_defs = []
    irq_defs = []
    analog_defs = []
    func_counts = defaultdict(int)  # For numbering non-SCI functions

    HEADER_GUARD = "__ARCH_ARM_SRC_RA_HARDWARE_RA8E1_PINMAP_H"

    # Process each pin to generate alternative function definitions
    for pin_name, data in sorted(pins_data.items()):
        port = data['port']
        pin = data['pin']

        for func in data['functions']:
            # Generate IRQ Definitions
            if 'IRQ' in func:
                irq_match = re.search(r'IRQ(\d+)', func)
                if irq_match:
                    irq_num = irq_match.group(1)
                    ds_suffix = "_DS" if "-DS" in func else ""
                    irq_def = f"#define GPIO_IRQ{irq_num}_{pin_name}{ds_suffix}                      (gpio_pinset_t){{ PORT{port}, PIN{pin}, (GPIO_INPUT | R_PFS_PCR | R_PFS_ISEL)}}"
                    if irq_def not in irq_defs:
                        irq_defs.append(irq_def)

            # Generate Analog Definitions
            elif func.startswith('AN') or func.startswith('DA'):
                analog_def = f"#define GPIO_{func}_1                        (gpio_pinset_t){{ PORT{port}, PIN{pin}, (0 | R_PFS_ASEL)}}"
                if analog_def not in analog_defs:
                    analog_defs.append(analog_def)

            # Generate Alternative Function Definitions
            else:
                psel = get_psel_value(func)
                if psel:
                    # Use the new function mapping for shortened names
                    clean_func = create_function_mapping(func)

                    # Check if this is a SCI function (already has A/B/C suffix)
                    if ('RXD' in clean_func or 'TXD' in clean_func) and clean_func.endswith(('_A', '_B', '_C')):
                        # SCI functions already have their suffix, use as-is
                        alt_func_def = f"#define GPIO_{clean_func}                         (gpio_pinset_t){{ PORT{port}, PIN{pin}, ({psel} | R_PFS_PMR)}}"
                    else:
                        # Other functions use numbered suffixes
                        func_counts[clean_func] += 1
                        count = func_counts[clean_func]
                        alt_func_def = f"#define GPIO_{clean_func}_{count}                         (gpio_pinset_t){{ PORT{port}, PIN{pin}, ({psel} | R_PFS_PMR)}}"

                    alt_func_defs.append(alt_func_def)

    # Print the header file
    print(f"""/****************************************************************************
 * arch/arm/src/ra8/hardware/ra8e1_pinmap.h
 *
 * GENERATED BY SCRIPT - DO NOT EDIT MANUALLY
 *
 ****************************************************************************/

#ifndef {HEADER_GUARD}
#define {HEADER_GUARD}

/****************************************************************************
 * Included Files
 ****************************************************************************/

#include <nuttx/config.h>
#include "chip.h"
#include "hardware/ra_memorymap.h"

/****************************************************************************
 * Pre-processor Definitions
 ****************************************************************************/

/* Alternative Function Pin Definitions */
{chr(10).join(sorted(alt_func_defs))}

/* External Interrupt Pin Definitions */
{chr(10).join(sorted(list(set(irq_defs))))}

/* Analog Input Definitions */
{chr(10).join(sorted(list(set(analog_defs))))}

/* General Purpose GPIO Pin Definitions */
""")

    # Generate GPIO pin definitions
    for pin_name, data in sorted(pins_data.items()):
        port = data['port']
        pin = data['pin']

        print(f"/* {pin_name} Pin Definitions */")
        print(f"#define GPIO_{pin_name}_OUTPUT_HIGH               (gpio_pinset_t){{ PORT{port}, PIN{pin}, (GPIO_OUTPUT | GPIO_LOW_DRIVE | GPIO_OUTPUT_HIGH)}}")
        print(f"#define GPIO_{pin_name}_OUTPUT_LOW                (gpio_pinset_t){{ PORT{port}, PIN{pin}, (GPIO_OUTPUT | GPIO_LOW_DRIVE | GPIO_OUTPUT_LOW)}}")
        print(f"#define GPIO_{pin_name}_INPUT                     (gpio_pinset_t){{ PORT{port}, PIN{pin}, (GPIO_INPUT)}}")
        print(f"#define GPIO_{pin_name}_INPUT_PULLUP              (gpio_pinset_t){{ PORT{port}, PIN{pin}, (GPIO_INPUT | R_PFS_PCR)}}")

        # Add analog capability if the pin has ANxxx function
        if any(f.startswith('AN') or f.startswith('DA') for f in data['functions']):
            print(f"#define GPIO_{pin_name}_ANALOG                    (gpio_pinset_t){{ PORT{port}, PIN{pin}, (0 | R_PFS_ASEL)}}")

        print("")

    print(f"/* GPIO Configuration */")
    print(f"#define GPIO_OUTPUT               R_PFS_PDR")
    print(f"#define GPIO_INPUT               ~(R_PFS_PDR | 0xFFFFFFFF)")
    print(f"#define GPIO_LOW_DRIVE          ~(R_PFS_DSCR | 0xFFFFFFFF)")
    print(f"#define GPIO_MIDDLE_DRIVE       R_PFS_DSCR")
    print(f"#define GPIO_OUTPUT_HIGH         R_PFS_PODR")
    print(f"#define GPIO_OUTPUT_LOW         ~(R_PFS_PODR | 0xFFFFFFFF)")
    print(f"")
    print(f"#endif /* {HEADER_GUARD} */")

if __name__ == "__main__":
    generate_header()