import os
import asyncio
import time

from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.widgets import RichLog

uart0 = RichLog(markup=True, auto_scroll=True)
uart1 = RichLog(markup=True, auto_scroll=True)

class Monitor(App):
    BINDINGS = [("ctrl+x", "quit", "Quit")]

    CSS = """
    Horizontal { height: 100%; }
    RichLog { width: 1fr; border: solid green; }
    """

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield uart0
            yield uart1

    def on_mount(self):
        uart0.border_title = "UART0"
        uart1.border_title = "UART1"
        self.run_worker(main())

# AI-GENERATED FUNCTION, REVIEW
def base36(n: int) -> str:
    chars = "0123456789abcdefghijklmnopqrstuvwxyz"

    if n == 0:
        return "0"

    sign = "-" if n < 0 else ""
    n = abs(n)
    result = ""

    while n:
        n, rem = divmod(n, 36)
        result = chars[rem] + result

    return sign + result

def concati(*nr: int) -> int:
    x = 0x0

    for n in nr:
        if n >= 256:
            raise ValueError("Overflow in concati, overflow unexpected (?)")
        x = x << 8
        x += n

    return x

class Memory:
    def __init__(self):
        self.mem = [0x0 for i in range(16 * 4096)]  # 16KiB
    
    async def i8(self, memaddr: int):  # MEMORY ADDRESS INDEXES BYTES
        return self.mem[memaddr]

    async def i32(self, memaddr: int):  # MEMORY ADDRESS INDEXES BYTES
        return concati(*self.mem[memaddr:memaddr+4])

    async def wi32(self, memaddr: int, value: int):  # MEMORY ADDRESS INDEXES BYTES
        if value > 0xffffffff:
            raise ValueError("OVERFLOW IN MEMORY WRITE WI32")

        self.mem[memaddr] = value >> 24
        self.mem[memaddr+1] = (value >> 16) & 0xff
        self.mem[memaddr+2] = (value >> 8) & 0xff
        self.mem[memaddr+3] = value & 0xff

CPU_HERTZ = 1 / 32  # 32 Hz

class CPU:
    def __init__(self, cpu_id: int, memory: Memory):
        self.cpi = 0x0  # Code Pointer Index
        self.fmpea = 0x0  # Firmware Memory Protection Entries Address
        self.regs = [0x0 for i in range(16)]
        self.clock: int = 0x0
        self.running = 0x1 if cpu_id == 0 else 0x0
        self._cpu_id = cpu_id

        self._memory = memory

    async def debug_msg(self, text: str):
        uart0.write(f"[mono]cpu-{self._cpu_id} | {self.clock} | {text}")

    async def _run(self):
        start = time.perf_counter()

        instruction = await self._memory.i8(self.cpi)
        self.cpi += 1
        if instruction == 0xff:
            instruction = await self._memory.i32(self.cpi)
            self.cpi += 4

        match instruction:
            case 0x0:  # NOP
                await self.debug_msg(f"[dim](NOP)[/] 0x0")

            case 0x1:  # EXIT
                await self.debug_msg(f"[dim](EXIT)[/] [red bright]0x1[/]")
                return True

            case 0x2:  # PUTC [value]
                value = await self._memory.i8(self.cpi)
                self.cpi += 1
                str_byte = value.to_bytes(1, 'little').decode('utf-8')
                uart1.write(str_byte)
                await self.debug_msg(f"[dim](PUTC)[/] 0x2 [dim]\\[value] ({str_byte})[/] {hex(value)}")

            case 0x3:  # PUTC_MEM [memaddr [value]]
                addr = await self._memory.i32(self.cpi)
                self.cpi += 4
                value = await self._memory.i8(addr)
                str_byte = value.to_bytes(1, 'little').decode('utf-8')
                uart1.write(str_byte)
                await self.debug_msg(f"[dim](PUTC_MEM)[/] 0x3 [dim]\\[memaddr [value]] ({addr} [value] ({value}))[/] {hex(addr)}")

            case 0x4:  # EQ [dest] [reg1] [reg2]
                dest_reg = await self._memory.i8(self.cpi)
                self.cpi += 1
                reg1 = await self._memory.i8(self.cpi)
                self.cpi += 1
                reg2 = await self._memory.i8(self.cpi)
                self.cpi += 1
                self.regs[dest_reg] = 0x1 if self.regs[reg1] == self.regs[reg2] else 0x0
                await self.debug_msg(f"[dim](EQ)[/] 0x4 [dim]\\[dest][/] r{dest_reg} [dim]\\[dest][/] r{dest_reg} [dim]\\[dest][/] r{dest_reg}")

            case 0x5:  # JMP [memaddr]
                addr = await self._memory.i32(self.cpi)
                self.cpi = addr
                await self.debug_msg(f"[dim](JMP)[/] 0x5 [dim]\\[memaddr][/] {hex(addr)}")

            case 0x6:  # JMPIF [reg1] [memaddr]
                reg1 = await self._memory.i8(self.cpi)
                self.cpi += 1
                memaddr = await self._memory.i32(self.cpi)
                self.cpi += 4
                if self.regs[reg1] != 0x0:
                    self.cpi = memaddr

                await self.debug_msg(f"[dim](JMP)[/] 0x5 [dim]\\[reg1][/] r{reg1} [dim]\\[memaddr][/] {hex(memaddr)}")

            case 0x7:  # MOV [reg1] [dest_reg]
                reg1 = await self._memory.i8(self.cpi)
                self.cpi += 1
                dest_reg = await self._memory.i8(self.cpi)
                self.cpi += 1
                self.regs[dest_reg] = self.regs[reg1]

            case 0x8:  # MVCONST [value] [dest_reg]
                value = await self._memory.i32(self.cpi)
                self.cpi += 4
                dest_reg = await self._memory.i8(self.cpi)
                self.cpi += 1
                self.regs[dest_reg] = value
                await self.debug_msg(f"[dim](MVCONST)[/] 0x8 [dim]\\[value] ({value})[/] {hex(value)} [dim]\\[dest_reg][/] r{dest_reg}")

            case 0x9:  # READ [memaddr [value]] [dest_reg]
                memaddr = await self._memory.i32(self.cpi)
                self.cpi += 4
                value = await self._memory.i32(memaddr)
                dest_reg = await self._memory.i8(self.cpi)
                self.cpi += 1
                self.regs[dest_reg] = value

            case 0xa:  # WRITE [src_reg] [memaddr]
                src_reg = await self._memory.i8(self.cpi)
                self.cpi += 1
                memaddr = await self._memory.i32(self.cpi)
                self.cpi += 4
                await self._memory.wi32(memaddr, self.regs[src_reg])

            case 0xb:  # FIRMWARE
                self.regs[0] = self.cpi
                self.cpi = 0x0

            case 0xc:  # INCR [reg]
                reg = await self._memory.i8(self.cpi)
                self.cpi += 1
                self.regs[reg] += 1

            case 0xd:  # READ.REG [addr_reg] [target_reg]
                addr_reg = await self._memory.i8(self.cpi)
                self.cpi += 1
                target_reg = await self._memory.i8(self.cpi)
                self.cpi += 1
                self.regs[target_reg] = await self._memory.i32(self.regs[addr_reg])

            case 0xe:  # ADD [reg1] [reg2] [dest_reg]
                reg1 = await self._memory.i8(self.cpi)
                self.cpi += 1
                reg2 = await self._memory.i8(self.cpi)
                self.cpi += 1
                dest_reg = await self._memory.i8(self.cpi)
                self.cpi += 1
                self.regs[dest_reg] = (self.regs[reg1] + self.regs[reg2]) & 0xffffffff

            case 0xf:  # JMP.REG [reg]
                reg = await self._memory.i8(self.cpi)
                addr = self.regs[reg]
                self.cpi = addr

            case op:
                raise ValueError(f"SIGILL: {hex(op)}")

        end = time.perf_counter()

        await asyncio.sleep(max(CPU_HERTZ - (end - start) % CPU_HERTZ, 0))

        cpu_cycles = (time.perf_counter() - start) // CPU_HERTZ
        self.clock += int(cpu_cycles)

async def main(): 
    mem = Memory()
    with open("mem.bin", "rb") as f:
        for i, b in enumerate(f.read()):
            mem.mem[i] = b
            
    cpu = CPU(0, mem)
    for i in range(256):
        if await cpu._run():
            break

Monitor().run()
