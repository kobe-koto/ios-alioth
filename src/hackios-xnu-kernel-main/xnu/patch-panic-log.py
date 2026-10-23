"""Put the panic text into the loader's log, so that a panic on the phone can be read afterwards.

There is no serial port on this device and no debugger is attached; the console the kernel does have
(the panel) is not written to on the panic path, so panic()'s message is formatted and handed to the
debugger machinery, and dropped. The loader's log outlives the kernel and is read with "oem log".
"""
import sys

PATH = sys.argv[1] if len(sys.argv) > 1 else "xnu-src/xnu-8796.121.2/osfmk/kern/debug.c"

ANCHOR = """	/* do max nested panic/debugger check, this will report nesting to the console and spin forever if we exceed a limit */
	check_and_handle_nested_panic(panic_options_mask, panic_caller, panic_format_str, panic_args);
"""

ADDITION = """
	/*
	 * No serial port, no debugger, and the console this kernel does have is not written to on this
	 * path: the panic's text would be lost. Put it in the loader's log, which outlives the kernel.
	 */
	{
		extern void loader_log_putc(char c);
		static const char panic_banner[] = "\\n--- panic ---\\n";

		for (const char *c = panic_banner; *c != 0; c++) {
			loader_log_putc(*c);
		}
		_doprnt(panic_format_str, panic_args, loader_log_putc, 0);
		loader_log_putc('\\n');
	}
"""

text = open(PATH, encoding="utf-8", errors="surrogateescape").read()
if "panic_banner" in text:
    print("already there")
    raise SystemExit(0)
if ANCHOR not in text:
    raise SystemExit("panic-log hook: anchor not found in " + PATH)
text = text.replace(ANCHOR, ANCHOR + ADDITION, 1)
open(PATH, "w", encoding="utf-8", errors="surrogateescape").write(text)
print("panic-log hook: inserted into " + PATH)
