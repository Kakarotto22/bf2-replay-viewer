// Ghidra headless script: print consecutive 32-bit pointers (a vtable) and the function each one points to.
// Usage: -postScript DumpPointers.java <outPath> <0xaddress+count>
// @category REA
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import java.io.FileWriter;
import java.io.PrintWriter;

public class DumpPointers extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        String[] spec = args[1].split("[+]");
        Address base = toAddr(Long.decode(spec[0]));
        int count = Integer.parseInt(spec[1]);
        PrintWriter out = new PrintWriter(new FileWriter(args[0]));
        for (int i = 0; i < count; i++) {
            Address at = base.add(4L * i);
            long value = currentProgram.getMemory().getInt(at) & 0xffffffffL;
            Function f = getFunctionAt(toAddr(value));
            out.println(String.format("slot %2d  %s -> %08x  %s", i, at, value, f == null ? "-" : f.getName()));
        }
        out.close();
    }
}
