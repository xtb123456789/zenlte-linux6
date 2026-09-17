#!/usr/bin/env python3
"""
Custom Samsung Exynos 7420 (SM-G9280) boot.img packager.
Matches Samsung official format and SHA-1 checksum verification bit-for-bit.
"""

import sys
import os
import struct
import hashlib

PAGE_SIZE = 2048

def align(size):
    return (size + PAGE_SIZE - 1) & ~(PAGE_SIZE - 1)

def pack_bootimg(kernel_path, ramdisk_path, dtb_path, output_path, cmdline=""):
    with open(kernel_path, 'rb') as f:
        k_data = f.read()
    with open(ramdisk_path, 'rb') as f:
        r_data = f.read()
    with open(dtb_path, 'rb') as f:
        dt_data = f.read()

    # Calculate SHA-1 checksum
    sha = hashlib.sha1()
    sha.update(k_data)
    sha.update(len(k_data).to_bytes(4, 'little'))
    sha.update(r_data)
    sha.update(len(r_data).to_bytes(4, 'little'))
    sha.update(b'')
    sha.update(int(0).to_bytes(4, 'little'))
    sha.update(dt_data)
    sha.update(len(dt_data).to_bytes(4, 'little'))
    digest = sha.digest()

    # Header: 2048 bytes
    hdr = bytearray(PAGE_SIZE)
    hdr[0:8] = b'ANDROID!'
    struct.pack_into('<IIIIIIIII', hdr, 8,
        len(k_data), 0x10008000,
        len(r_data), 0x11000000,
        0, 0x10f00000,
        0x10000100, PAGE_SIZE,
        len(dt_data)
    )
    hdr[48:60] = b'SYSMAGIC000K'
    if cmdline:
        cmd_bytes = cmdline.encode('latin1')[:512]
        hdr[64:64+len(cmd_bytes)] = cmd_bytes

    # Copy 20-byte SHA-1 digest into id field (offset 576)
    hdr[576:576+len(digest)] = digest

    # Assemble payload
    bootimg = bytearray(hdr)
    bootimg.extend(k_data)
    bootimg.extend(b'\x00' * (align(len(k_data)) - len(k_data)))

    bootimg.extend(r_data)
    bootimg.extend(b'\x00' * (align(len(r_data)) - len(r_data)))

    bootimg.extend(dt_data)
    bootimg.extend(b'\x00' * (align(len(dt_data)) - len(dt_data)))

    # Samsung SBOOT trailer
    bootimg.extend(b'SEANDROIDENFORCE\x02\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00')

    with open(output_path, 'wb') as f:
        f.write(bootimg)

    print(f"[+] Successfully packed {output_path}:")
    print(f"    Kernel : {len(k_data)} bytes (0x{len(k_data):x})")
    print(f"    Ramdisk: {len(r_data)} bytes (0x{len(r_data):x})")
    print(f"    DTB    : {len(dt_data)} bytes (0x{len(dt_data):x})")
    print(f"    Total  : {len(bootimg)} bytes ({len(bootimg)/(1024*1024):.2f} MB)")
    print(f"    SHA-1  : {sha.hexdigest()}")

if __name__ == '__main__':
    if len(sys.argv) < 5:
        print(f"Usage: {sys.argv[0]} <kernel> <ramdisk.cpio.gz> <dt.img> <output.img> [cmdline]")
        sys.exit(1)
    cmdline = sys.argv[5] if len(sys.argv) > 5 else ""
    pack_bootimg(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], cmdline)
