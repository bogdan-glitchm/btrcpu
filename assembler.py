"""Simple two-pass assembler for the BTR CPU."""

import argparse
import ast
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Instruction:
    opcode: int
    operands: tuple[int | str, ...] = ()  # Byte width, or "r" for a register


# Operand types: 1 = byte, 4 = 32-bit big-endian value, "r" = register r0-r15.
# Register operands also accept numeric 0-15 for backwards compatibility.
INSTRUCTIONS = {
    "NOP": Instruction(0x00),
    "EXIT": Instruction(0x01),
    "PUTC": Instruction(0x02, (1,)),
    "PUTC_MEM": Instruction(0x03, (4,)),
    "EQ": Instruction(0x04, ("r", "r", "r")),
    "JMP": Instruction(0x05, (4,)),
    "JMPIF": Instruction(0x06, ("r", 4)),
    "MOV": Instruction(0x07, ("r", "r")),
    "MVCONST": Instruction(0x08, (4, "r")),
    "READ": Instruction(0x09, (4, "r")),
    "WRITE": Instruction(0x0A, ("r", 4)),
    "FIRMWARE": Instruction(0x0B),
    "INCR": Instruction(0x0C, ("r",)),
    "READ.REG": Instruction(0x0D, ("r", "r")),
    "ADD": Instruction(0x0E, ("r", "r", "r")),
    "JMP.REG": Instruction(0xF, ("r",))
}

# Directives that emit one or more fixed-width values.
DATA_DIRECTIVES = {".BYTE": 1, ".DWORD": 4}


def strip_comment(line: str) -> str:
    """Remove ';' comments, except when the semicolon is inside a string."""
    quote = None
    escaped = False

    for i, char in enumerate(line):
        if escaped:
            escaped = False
        elif char == "\\" and quote:
            escaped = True
        elif char in ('"', "'"):
            if quote is None:
                quote = char
            elif quote == char:
                quote = None
        elif char == ";" and quote is None:
            return line[:i]

    return line


def string_bytes(text: str) -> bytes:
    """Convert a quoted string (including escapes) into UTF-8 bytes."""
    try:
        value = ast.literal_eval(text)
    except (SyntaxError, ValueError):
        raise ValueError(".STRING expects a quoted string") from None

    if not isinstance(value, str):
        raise ValueError(".STRING expects a quoted string")

    return value.encode("utf-8")


def encode_opcode(opcode: int) -> bytes:
    """Use one byte for normal opcodes; 0xFF + four bytes for extended ones."""
    if 0 <= opcode < 0xFF:
        return bytes([opcode])
    if 0xFF <= opcode <= 0xFFFFFFFF:
        return b"\xFF" + opcode.to_bytes(4, "big")
    raise ValueError(f"Invalid opcode: {opcode}")


def encode_value(value: int, width: int) -> bytes:
    """Encode an unsigned integer in big-endian byte order."""
    if not 0 <= value < (1 << (8 * width)):
        raise ValueError(f"{value} does not fit in {width} byte(s)")
    return value.to_bytes(width, "big")


def register_number(value: str) -> int:
    """Convert r0-r15 to a register index; also accept plain 0-15."""
    if re.fullmatch(r"[rR]\d+", value):
        number = int(value[1:])
    else:
        try:
            number = int(value, 0)
        except ValueError:
            raise ValueError(f"Invalid register: {value!r} (expected r0-r15)") from None

    if not 0 <= number < 16:
        raise ValueError(f"Invalid register: {value!r} (expected r0-r15)")
    return number


def operand_width(kind: int | str) -> int:
    """Registers always occupy one byte in machine code."""
    return 1 if kind == "r" else kind


def resolve(value: str, labels: dict[str, int]) -> int:
    """Resolve a label or parse a decimal, hexadecimal, or binary integer."""
    if value in labels:
        return labels[value]
    try:
        return int(value, 0)
    except ValueError:
        raise ValueError(f"Unknown number or label: {value!r}") from None


def assemble(source: str) -> bytes:
    """Assemble source text into raw machine code."""
    labels = {}
    statements = []
    pc = 0  # Current byte offset in the output

    # PASS 1: Find label addresses and calculate statement sizes.
    for line_no, raw in enumerate(source.splitlines(), 1):
        line = strip_comment(raw).strip()
        if not line:
            continue

        # Labels refer to the address of the next emitted byte.
        while match := re.match(r"^([A-Za-z_]\w*):\s*(.*)$", line):
            label, line = match.groups()
            if label in labels:
                raise ValueError(f"Line {line_no}: duplicate label {label!r}")
            labels[label] = pc
            line = line.strip()

        if not line:
            continue

        parts = line.split(None, 1)
        name = parts[0].upper()
        text = parts[1].strip() if len(parts) > 1 else ""

        # A string must stay in one piece; other operands use commas/spaces.
        if name in (".STRING", ".STR"):
            args = (text,) if text else ()
            name = ".STRING"
        else:
            args = tuple(x for x in re.split(r"[,\s]+", text) if x)

        # PUTC [address] reads memory; PUTC value uses an immediate byte.
        if name == "PUTC" and len(args) == 1 and args[0].startswith("[") and args[0].endswith("]"):
            name = "PUTC_MEM"
            args = (args[0][1:-1],)

        try:
            if name in INSTRUCTIONS:
                ins = INSTRUCTIONS[name]
                if len(args) != len(ins.operands):
                    raise ValueError(f"{name} expects {len(ins.operands)} operands")
                size = len(encode_opcode(ins.opcode)) + sum(operand_width(kind) for kind in ins.operands)

            elif name in DATA_DIRECTIVES:
                if not args:
                    raise ValueError(f"{name} expects at least one value")
                size = len(args) * DATA_DIRECTIVES[name]

            elif name == ".STRING":
                if not args:
                    raise ValueError(".STRING expects a quoted string")
                size = len(string_bytes(args[0]))

            elif name in (".REPEAT", ".PAD"):
                if len(args) != 2:
                    raise ValueError(f"{name} expects 2 operands")
                amount = int(args[0], 0)  # Sizes must be known in pass 1.

                if name == ".REPEAT":
                    if amount < 0:
                        raise ValueError(".REPEAT count must be nonnegative")
                    size = amount
                else:
                    if amount <= 0:
                        raise ValueError(".PAD divisor must be positive")
                    size = (-pc) % amount  # Align the next byte's address.

            else:
                raise ValueError(f"Unknown instruction: {name}")

        except ValueError as error:
            raise ValueError(f"Line {line_no}: {error}") from error

        statements.append((line_no, name, args, size))
        pc += size

    # PASS 2: Resolve labels and emit machine code.
    output = bytearray()
    for line_no, name, args, size in statements:
        try:
            if name == ".STRING":
                output.extend(string_bytes(args[0]))

            elif name in (".REPEAT", ".PAD"):
                byte = encode_value(resolve(args[1], labels), 1)
                output.extend(byte * size)

            else:
                if name in INSTRUCTIONS:
                    ins = INSTRUCTIONS[name]
                    output.extend(encode_opcode(ins.opcode))
                    kinds = ins.operands
                else:
                    kinds = (DATA_DIRECTIVES[name],) * len(args)

                for arg, kind in zip(args, kinds):
                    if kind == "r":
                        # r7 is stored as a single byte with value 7.
                        output.append(register_number(arg))
                    else:
                        output.extend(encode_value(resolve(arg, labels), kind))

        except ValueError as error:
            raise ValueError(f"Line {line_no}: {error}") from error

    return bytes(output)


def main():
    parser = argparse.ArgumentParser(description="Assemble BTR CPU programs")
    parser.add_argument("path", help="Input assembly file")
    parser.add_argument("-o", "--output", help="Output binary file")
    parser.add_argument(
        "--no-firmware",
        action="store_true",
        help="Do not prepend firm.btrm",
    )
    args = parser.parse_args()

    # Load the user's source file.
    source = Path(args.path).read_text(encoding="utf-8")

    # By default, firmware is inserted first, so its code starts at address 0.
    # Assemble the combined source once so labels work across both files.
    if not args.no_firmware:
        firmware_path = Path(__file__).resolve().with_name("firm.btrm")
        firmware = firmware_path.read_text(encoding="utf-8")
        source = firmware + "\n" + source

    code = assemble(source)

    # Either write a binary file or display the generated machine code.
    if args.output:
        Path(args.output).write_bytes(code)
        print(f"Wrote {len(code)} bytes to {args.output}")
    else:
        print(code.hex(" "))


if __name__ == "__main__":
    main()
