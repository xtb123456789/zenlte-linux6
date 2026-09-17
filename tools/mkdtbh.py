#!/usr/bin/env python3
"""
Samsung DTBH format packager for Exynos 7420.
Constructs multi-DTB dt.img matching S-Boot 4.0 specification.
"""

import sys
import os
import struct

PAGE_SIZE = 2048

def align(size):
    return (size + PAGE_SIZE - 1) & ~(PAGE_SIZE - 1)

def pack_dtb(dtb_path, output_path, chip_id=0x1cfc, plat_id=0x50a6, sub_id=0x217584da):
    with open(dtb_path, 'rb') as f:
        dtb_data = f.read()

    dtb_len = len(dtb_data)

    # Revisions covering all variants, especially rev 9 (SM-G9280)
    hw_revs = [
        (0x0, 0x0),
        (0x1, 0x1),
        (0x2, 0x2),
        (0x3, 0x3),
        (0x4, 0x7),
        (0x8, 0x8),
        (0x9, 0xff), # Primary match for SM-G9280 (hw_rev 9)
    ]
    num_dtbs = len(hw_revs)

    # Header: Magic 'DTBH', version 2, num_dtbs
    hdr = bytearray()
    hdr.extend(b'DTBH')
    hdr.extend(struct.pack('<II', 2, num_dtbs))

    # Entry size: chip(4) + plat(4) + sub(4) + rev_start(4) + rev_end(4) + offset(4) + size(4) + space(4) = 32 bytes
    entry_size = 32
    table_size = 12 + num_dtbs * entry_size
    first_dtb_offset = align(table_size)

    # Prepare entries
    entries = bytearray()
    current_offset = first_dtb_offset

    for rev_start, rev_end in hw_revs:
        # extra field is 0x20 (the entry size itself)
        entry = struct.pack('<IIIIIIII', chip_id, plat_id, sub_id, rev_start, rev_end, current_offset, dtb_len, 0x20)
        entries.extend(entry)

    # Assemble file
    out = bytearray()
    out.extend(hdr)
    out.extend(entries)
    out.extend(b'\x00' * (first_dtb_offset - len(out)))
    out.extend(dtb_data)
    out.extend(b'\x00' * (align(len(out)) - len(out)))

    with open(output_path, 'wb') as f:
        f.write(out)

    print(f"[+] Successfully generated {output_path}:")
    print(f"    Entries : {num_dtbs} (matching hw_rev 0x0..0xff)")
    print(f"    DTB Size: {dtb_len} bytes")
    print(f"    Total   : {len(out)} bytes ({len(out)/1024:.1f} KB)")

if __name__ == '__main__':
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <input.dtb> <output_dt.img>")
        sys.exit(1)
    pack_dtb(sys.argv[1], sys.argv[2])
