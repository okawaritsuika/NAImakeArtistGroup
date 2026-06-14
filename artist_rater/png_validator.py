import struct
import zlib


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
MAX_PNG_DIMENSION = 2048
MAX_SCANLINE_BYTES = 32 * 1024 * 1024


def validate_png(png_bytes, expected_width=None, expected_height=None):
    if not isinstance(png_bytes, (bytes, bytearray)):
        raise ValueError("PNG data must be bytes.")
    data = bytes(png_bytes)
    if not data.startswith(PNG_SIGNATURE):
        raise ValueError("Data is not a PNG image.")

    offset = len(PNG_SIGNATURE)
    chunk_index = 0
    saw_idat = False
    saw_iend = False
    idat_parts = []
    image_height = None
    expected_length = None
    row_bytes = None
    while offset < len(data):
        if len(data) - offset < 12:
            raise ValueError("PNG chunk is truncated.")
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        chunk_type = data[offset + 4 : offset + 8]
        chunk_end = offset + 12 + length
        if chunk_end > len(data):
            raise ValueError("PNG chunk is truncated.")
        chunk_data = data[offset + 8 : offset + 8 + length]
        expected_crc = struct.unpack(">I", data[offset + 8 + length : chunk_end])[0]
        actual_crc = zlib.crc32(chunk_type)
        actual_crc = zlib.crc32(chunk_data, actual_crc) & 0xFFFFFFFF
        if actual_crc != expected_crc:
            raise ValueError("PNG chunk CRC is invalid.")

        if chunk_index == 0:
            if chunk_type != b"IHDR" or length != 13:
                raise ValueError("PNG must start with a valid IHDR chunk.")
            width, height, bit_depth, color_type, compression, filtering, interlace = (
                struct.unpack(">IIBBBBB", chunk_data)
            )
            valid_depths = {
                0: {1, 2, 4, 8, 16},
                2: {8, 16},
                3: {1, 2, 4, 8},
                4: {8, 16},
                6: {8, 16},
            }
            if (
                not 1 <= width <= MAX_PNG_DIMENSION
                or not 1 <= height <= MAX_PNG_DIMENSION
                or bit_depth not in valid_depths.get(color_type, set())
                or compression != 0
                or filtering != 0
            ):
                raise ValueError("PNG IHDR fields are invalid.")
            if interlace != 0:
                raise ValueError("Interlaced PNG images are not supported.")
            if expected_width is not None and width != int(expected_width):
                raise ValueError("PNG dimensions do not match the request.")
            if expected_height is not None and height != int(expected_height):
                raise ValueError("PNG dimensions do not match the request.")
            channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color_type]
            row_bytes = (width * channels * bit_depth + 7) // 8
            expected_length = height * (1 + row_bytes)
            if expected_length > MAX_SCANLINE_BYTES:
                raise ValueError("PNG scanline data exceeds the allowed size.")
            image_height = height
        elif chunk_type == b"IHDR":
            raise ValueError("PNG contains multiple IHDR chunks.")

        if chunk_type == b"IDAT":
            saw_idat = True
            idat_parts.append(chunk_data)
        if chunk_type == b"IEND":
            if length != 0 or not saw_idat:
                raise ValueError("PNG IEND or IDAT structure is invalid.")
            saw_iend = True
            if chunk_end != len(data):
                raise ValueError("PNG contains data after IEND.")
            break
        offset = chunk_end
        chunk_index += 1

    if not saw_iend or image_height is None:
        raise ValueError("PNG is missing IEND.")

    decompressor = zlib.decompressobj()
    scanlines = bytearray()
    try:
        for part in idat_parts:
            pending = part
            while pending:
                remaining = expected_length - len(scanlines)
                scanlines.extend(decompressor.decompress(pending, remaining + 1))
                if len(scanlines) > expected_length:
                    raise ValueError("PNG scanline data exceeds the expected length.")
                pending = decompressor.unconsumed_tail
                if pending and remaining == 0:
                    raise ValueError("PNG scanline data exceeds the expected length.")
        scanlines.extend(decompressor.flush(expected_length - len(scanlines) + 1))
    except zlib.error as exc:
        raise ValueError("PNG IDAT data is not valid zlib data.") from exc
    if len(scanlines) > expected_length:
        raise ValueError("PNG scanline data exceeds the expected length.")
    if not decompressor.eof or decompressor.unused_data or decompressor.unconsumed_tail:
        raise ValueError("PNG IDAT data is not a complete zlib stream.")
    if len(scanlines) != expected_length:
        raise ValueError("PNG scanline data has an invalid length.")
    for row in range(image_height):
        if scanlines[row * (1 + row_bytes)] not in range(5):
            raise ValueError("PNG scanline has an invalid filter type.")
    return data
