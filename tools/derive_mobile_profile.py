#!/usr/bin/env python3
"""Derive a local NeoLight ThingClips mobile profile from the official APK.

The script never prints keys or the derived BMP token. It writes a private JSON
profile file locally; do not upload that file to GitHub or include it in logs.
"""
from __future__ import annotations

import argparse
import json
import re
import zipfile
from fractions import Fraction
from pathlib import Path


class DecodeError(Exception):
    """The APK's BMP token could not be derived with the expected integral solve."""


def _strhash(value: bytes) -> int:
    value = value.split(b"\x00", 1)[0]
    acc = 0
    for byte in value:
        acc = (acc * 31 + byte) & 0xFFFFFFFF
    if acc >= 0x80000000:
        acc -= 0x100000000
    return abs(acc)


def _bmp_pixels(raw: bytes) -> tuple[int, bytes]:
    if raw[:2] != b"BM":
        raise DecodeError("t_s.bmp has an invalid BMP header.")
    file_size = int.from_bytes(raw[2:6], "little")
    pixel_offset = int.from_bytes(raw[10:14], "little")
    bpp = int.from_bytes(raw[0x1C:0x1E], "little")
    compression = int.from_bytes(raw[0x1E:0x22], "little")
    if (
        file_size >= 0x200001
        or file_size < 0x2800
        or file_size - 0x36 < pixel_offset
        or bpp not in (24, 32)
        or compression != 0
    ):
        raise DecodeError("t_s.bmp failed the SDK's header checks.")
    pixel_len = file_size - pixel_offset
    pixels = raw[0x36 : 0x36 + pixel_len]
    if len(pixels) != pixel_len:
        raise DecodeError("t_s.bmp pixel data is truncated.")
    return pixel_offset, pixels


def _xorstep(pixels: bytes, offset: int) -> int:
    size = len(pixels)
    return (
        (pixels[offset % size] << 24)
        | (pixels[(offset + 1) % size] << 16)
        | (pixels[(offset + 2) % size] << 8)
        | pixels[(offset + 3) % size]
    )


def _matrix_solve(pairs: list[tuple[str, str]]) -> bytes:
    def as_fraction(value: str) -> Fraction:
        if not value:
            return Fraction(0)
        if "/" in value:
            numerator, denominator = value.split("/", 1)
            return Fraction(int(numerator, 16), int(denominator, 16))
        return Fraction(int(value, 16))

    n = len(pairs)
    if not n:
        raise DecodeError("BMP matrix contained no coefficient pairs.")
    a_values = [as_fraction(a) for a, _ in pairs]
    b_values = [as_fraction(b) for _, b in pairs]
    matrix = [
        [a_values[i] ** (n - 1 - j) for j in range(n)] + [b_values[i]]
        for i in range(n)
    ]
    for column in range(n):
        pivot = next(
            (row for row in range(column, n) if matrix[row][column] != 0),
            None,
        )
        if pivot is None:
            raise DecodeError("BMP matrix solve was singular.")
        matrix[column], matrix[pivot] = matrix[pivot], matrix[column]
        for row in range(column + 1, n):
            if matrix[row][column]:
                factor = matrix[row][column] / matrix[column][column]
                for index in range(column, n + 1):
                    matrix[row][index] -= factor * matrix[column][index]
    denominator = matrix[n - 1][n - 1]
    if denominator == 0:
        raise DecodeError("BMP matrix solve was singular.")
    result = matrix[n - 1][n] / denominator
    if result.denominator != 1 or result.numerator < 0:
        raise DecodeError("BMP matrix solve failed the SDK's integral-result check.")
    number = result.numerator
    if number == 0:
        return b""
    return number.to_bytes((number.bit_length() + 7) // 8, "big").lstrip(b"\x00")


def _derive_bmp_token(raw_bmp: bytes, app_key: str) -> str:
    _, pixels = _bmp_pixels(raw_bmp)
    size = len(pixels)
    if not size:
        raise DecodeError("t_s.bmp has no pixel data.")
    hashed = _strhash(app_key.encode("utf-8"))
    offset_seed = (hashed % size) // 2
    base = offset_seed % size
    selector = pixels[base]
    if selector != 1:
        raise DecodeError(f"Unsupported BMP decoder selector ({selector}).")
    key_count = pixels[(base + 1) % size]
    coefficient_count = pixels[(base + 2) % size]
    if not (0 < key_count < 6) or coefficient_count == 0:
        raise DecodeError("BMP decoder returned invalid key/coefficient counts.")

    offset = (_xorstep(pixels, (base + 3) % size) ^ offset_seed) % size
    pairs: list[tuple[str, str]] = []
    for _ in range(coefficient_count):
        pair_start = offset
        a_len = pixels[offset % size]
        a = "".join(
            f"{pixels[(offset + 1 + i) % size]:02x}" for i in range(a_len)
        )
        after_a = (offset + 1 + a_len) % size
        b_len = pixels[after_a % size]
        b = "".join(
            f"{pixels[(after_a + 1 + i) % size]:02x}" for i in range(b_len)
        )
        offset = (after_a + 1 + b_len) % size
        pairs.append((a, b))
        offset = (_xorstep(pixels, offset) ^ pair_start) % size

    group_size = coefficient_count // key_count
    if group_size == 0:
        group_size = coefficient_count
    keys: list[str] = []
    for group in range(key_count):
        chunk = pairs[group * group_size : (group + 1) * group_size]
        if chunk:
            keys.append(_matrix_solve(chunk).hex())
    token = "_".join(keys)
    if not re.fullmatch(r"[0-9a-fA-F]{64}", token):
        raise DecodeError(
            "The derived token did not have the expected 64-hex-character format."
        )
    return token.lower()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("apk", type=Path, help="Official NeoLight 1.1.0 APK")
    parser.add_argument("profile", type=Path, help="Existing local mobile_profile.json")
    parser.add_argument(
        "output",
        type=Path,
        help="Destination for the corrected profile (keep this file private)",
    )
    args = parser.parse_args()

    try:
        profile = json.loads(args.profile.read_text(encoding="utf-8"))
        if not isinstance(profile, dict):
            raise ValueError("profile root must be an object")
        app_key = profile.get("app_key")
        if not isinstance(app_key, str) or len(app_key) != 20:
            raise ValueError("profile does not contain a valid app_key")
        with zipfile.ZipFile(args.apk) as archive:
            bmp = archive.read("assets/t_s.bmp")
        token = _derive_bmp_token(bmp, app_key)
        updated = dict(profile)
        updated.pop("embedded_key", None)
        updated["bmp_token"] = token
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(updated, indent=2) + "\n", encoding="utf-8"
        )
        try:
            args.output.chmod(0o600)
        except OSError:
            pass
    except (OSError, KeyError, ValueError, zipfile.BadZipFile, DecodeError) as err:
        print(f"Profile generation failed: {err}")
        return 1

    print("Corrected profile written. Secret values were not printed.")
    print("Use the output only in the NeoLight integration's local config folder.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
