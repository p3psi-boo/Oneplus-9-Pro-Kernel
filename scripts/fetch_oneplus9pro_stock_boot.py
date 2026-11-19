#!/usr/bin/env python3
"""Recover the exact OnePlus 9 Pro stock boot.img from its pinned full OTA.

Only read the ZIP directory, payload manifest and boot operations over HTTPS.
No software from the OTA is executed and no unverified image is returned.
"""
import argparse
import bz2
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import lzma
from pathlib import Path
import re
import struct
import tempfile
import time
from urllib import error, parse, request
import zipfile

from project import device, sha256


LIMIT = 64 * 1024 * 1024
RANGE = re.compile(r"bytes (\d+)-(\d+)/(\d+)")
CDN = {
    "gauss-componentotacostmanual-cn.allawnfs.com",
    "gauss-componentotamanual.allawnofs.com",
}


class RemoteZip(io.RawIOBase):
    def __init__(self, url):
        uri = parse.urlsplit(url)
        if uri.scheme != "https" or uri.netloc not in CDN or uri.query or uri.fragment:
            raise ValueError("Official pinned OnePlus OTA URL required")
        self.url = url
        self.position, self.size = 0, None
        self.get(0, 1)

    def get(self, start, length):
        if length == 0:
            return b""
        end = start + length - 1
        if start < 0 or not 0 < length <= LIMIT or (self.size is not None and end >= self.size):
            raise ValueError("Invalid OTA byte range")
        req = request.Request(self.url, headers={
            "Range": f"bytes={start}-{end}", "Accept-Encoding": "identity",
        })
        for attempt in range(3):
            try:
                with request.urlopen(req, timeout=45) as reply:
                    part = RANGE.fullmatch(reply.headers.get("Content-Range", ""))
                    if (reply.status != 206 or not part or parse.urlsplit(reply.geturl()).scheme != "https"
                            or tuple(map(int, part.groups()[:2])) != (start, end)):
                        raise ValueError("Official CDN did not return the requested HTTPS range")
                    size = int(part[3])
                    if size <= end or (self.size is not None and size != self.size):
                        raise ValueError("Official OTA size changed during extraction")
                    data = reply.read(length + 1)
                    if len(data) != length:
                        raise OSError("Truncated OTA range")
                    if self.size is None:
                        self.size = size
                    return data
            except error.HTTPError as exc:
                if exc.code not in (408, 429, 500, 502, 503, 504) or attempt == 2:
                    raise
            except OSError:
                if attempt == 2:
                    raise
            time.sleep(attempt + 1)
        raise RuntimeError("Unreachable range retry state")

    def seekable(self):
        return True

    def readable(self):
        return True

    def seek(self, offset, whence=io.SEEK_SET):
        position = {io.SEEK_SET: 0, io.SEEK_CUR: self.position, io.SEEK_END: self.size}[whence] + offset
        if position < 0:
            raise ValueError("Invalid ZIP seek")
        self.position = position
        return position

    def tell(self):
        return self.position

    def read(self, length=-1):
        available = max(0, self.size - self.position)
        length = available if length < 0 else min(available, length)
        data = self.get(self.position, length)
        self.position += len(data)
        return data


def varint(data, offset):
    value = 0
    for shift in range(0, 70, 7):
        if offset >= len(data):
            break
        byte = data[offset]
        offset += 1
        if shift == 63 and byte > 1:
            break
        value |= (byte & 127) << shift
        if byte < 128:
            return value, offset
    raise ValueError("Invalid OTA manifest integer")


def message(data):
    fields = defaultdict(list)
    offset = 0
    while offset < len(data):
        tag, offset = varint(data, offset)
        field, wire = divmod(tag, 8)
        if not field:
            raise ValueError("Invalid OTA manifest field")
        if wire == 0:
            value, offset = varint(data, offset)
        else:
            if wire == 2:
                length, offset = varint(data, offset)
            elif wire in (1, 5):
                length = 8 if wire == 1 else 4
            else:
                raise ValueError("Unsupported OTA manifest field")
            value = data[offset:offset + length]
            if len(value) != length:
                raise ValueError("Truncated OTA manifest field")
            offset += length
        fields[field].append(value)
    return fields


def one(fields, field, kind, default=None):
    values = fields.get(field, [])
    if not values and default is not None:
        return default
    if len(values) != 1 or not isinstance(values[0], kind):
        raise ValueError(f"Malformed OTA field {field}")
    return values[0]


def boot_plan(remote, firmware):
    size, digest = firmware["stock_boot_size"], bytes.fromhex(firmware["stock_boot_sha256"])
    with zipfile.ZipFile(remote) as archive:
        entries = [x for x in archive.infolist() if x.filename == "payload.bin"]
        if len(entries) != 1 or entries[0].compress_type != zipfile.ZIP_STORED:
            raise ValueError("Expected exactly one uncompressed payload.bin")
        entry = entries[0]
        header = remote.get(entry.header_offset, 30)
        if header[:4] != b"PK\x03\x04" or struct.unpack_from("<HH", header, 6)[1] != zipfile.ZIP_STORED:
            raise ValueError("Invalid ZIP local payload header")
        n, extra = struct.unpack_from("<HH", header, 26)
        name_at = entry.header_offset + 30
        if n != len(b"payload.bin") or remote.get(name_at, n) != b"payload.bin":
            raise ValueError("ZIP local payload name mismatch")
        start = name_at + n + extra
        end = start + entry.file_size
        magic, version, manifest_size, sig_size = struct.unpack(">4sQQI", remote.get(start, 24))
        data_start = start + 24 + manifest_size + sig_size
        if magic != b"CrAU" or version != 2 or not 0 < manifest_size <= LIMIT or sig_size > (1 << 20) or data_start > end:
            raise ValueError("Unsupported OTA payload header")
        manifest = message(remote.get(start + 24, manifest_size))

    block = one(manifest, 3, int, 4096)
    if block != 4096:
        raise ValueError("Unexpected OTA block size")
    partitions = [message(raw) for raw in manifest[13]]
    boot = [p for p in partitions if one(p, 1, bytes) == b"boot"]
    if len(boot) != 1:
        raise ValueError("OTA must contain one boot partition")
    info = message(one(boot[0], 7, bytes))
    if one(info, 1, int) != size or one(info, 2, bytes) != digest:
        raise ValueError("OTA advertises a different stock boot image")

    ranges, plan = [], []
    for raw in boot[0][8]:
        op = message(raw)
        mode = one(op, 1, int)
        extents = []
        for extent in op[6]:
            extent = message(extent)
            offset, length = one(extent, 1, int) * block, one(extent, 2, int) * block
            if not length or offset + length > size:
                raise ValueError("Boot extent exceeds stock partition")
            extents.append((offset, length))
            ranges.append((offset, length))
        plain_size = sum(length for _, length in extents)
        if not 0 < plain_size <= size:
            raise ValueError("Invalid OTA boot operation extent size")
        if mode in (6, 7):  # ZERO or DISCARD. Exact final digest is still mandatory.
            if one(op, 3, int, 0):
                raise ValueError("Unexpected data attached to an empty boot operation")
            plan.append((mode, 0, 0, b"", extents, plain_size))
        elif mode in (0, 1, 8):  # REPLACE, REPLACE_BZ, REPLACE_XZ in a full OTA.
            start_at = data_start + one(op, 2, int, 0)
            length = one(op, 3, int)
            digest_at = one(op, 8, bytes)
            if not 0 < length <= LIMIT or start_at + length > end or len(digest_at) != 32:
                raise ValueError("Invalid OTA boot data range or checksum")
            plan.append((mode, start_at, length, digest_at, extents, plain_size))
        else:
            raise ValueError("Stock boot must not require a delta OTA source image")
    pos = 0
    for offset, length in sorted(ranges):
        if offset != pos:
            raise ValueError("OTA boot extents overlap or leave a hole")
        pos += length
    if pos != size:
        raise ValueError("OTA boot operations do not cover the stock partition")
    return plan


def payload_bytes(remote, item):
    mode, offset, length, expected_hash, _, total = item
    if mode in (6, 7):
        return None
    blob = remote.get(offset, length)
    if hashlib.sha256(blob).digest() != expected_hash:
        raise ValueError("OTA boot operation SHA-256 mismatch")
    if mode != 0:
        decoder = bz2.BZ2Decompressor() if mode == 1 else lzma.LZMADecompressor(memlimit=128 << 20)
        blob = decoder.decompress(blob, max_length=total + 1)
        if not decoder.eof or decoder.unused_data:
            raise ValueError("Invalid compressed OTA boot operation")
    if len(blob) != total:
        raise ValueError("OTA boot operation size mismatch")
    return blob


def fetch(firmware, output, remote_factory=RemoteZip):
    if output.exists():
        raise FileExistsError(output)
    remote = remote_factory(firmware["source_url"])
    plan = boot_plan(remote, firmware)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".ota-", dir=output.parent) as temp:
        path = Path(temp) / "boot.img"
        with path.open("w+b") as stream, ThreadPoolExecutor(max_workers=6) as workers:
            stream.truncate(firmware["stock_boot_size"])
            for item, blob in zip(plan, workers.map(lambda x: payload_bytes(remote, x), plan)):
                if blob is not None:
                    position = 0
                    for offset, length in item[4]:
                        stream.seek(offset)
                        stream.write(memoryview(blob)[position:position + length])
                        position += length
        if path.stat().st_size != firmware["stock_boot_size"] or sha256(path) != firmware["stock_boot_sha256"]:
            raise ValueError("Extracted boot image does not match the pinned stock SHA-256/size")
        # A hard link publishes the complete file without overwriting an existing path.
        output.hardlink_to(path)
    print(f"Verified original boot: {firmware['build_id']} / {sha256(output)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--os", required=True, choices=("coloros", "oxygenos"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    fetch(device("oneplus-9-pro")["firmware"][args.os], args.output)
