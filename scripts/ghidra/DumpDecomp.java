// Ghidra headless script: dump decompiled C for functions selected by name
// substring or by address. Usage:
//   -postScript DumpDecomp.java <outPath> <selector[,|+selector...]> [timeoutSeconds]  (use + on Windows: cmd splits on commas)
// Each selector is either a name substring or a 0x-prefixed address; a
// selector prefixed with '=' forces exact name match.
// @category REA
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionManager;
import java.io.FileWriter;
import java.io.PrintWriter;

public class DumpDecomp extends GhidraScript {
    private void dump(PrintWriter out, DecompInterface di, Function f, long timeout) {
        out.println("==== " + f.getEntryPoint() + "  " + f.getName()
                + "  (size=" + f.getBody().getNumAddresses() + ")");
        DecompileResults r = di.decompileFunction(f, (int) timeout, monitor);
        if (r != null && r.decompileCompleted()) {
            out.println(r.getDecompiledFunction().getC());
        } else {
            out.println("// decompile failed: " + (r != null ? r.getErrorMessage() : "null"));
        }
        out.println();
    }

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        String outPath = args.length > 0 ? args[0] : "decomp.txt";
        String specs = args.length > 1 ? args[1] : "deSerialize";
        long timeout = args.length > 2 ? Long.parseLong(args[2]) : 120;

        PrintWriter out = new PrintWriter(new FileWriter(outPath));
        DecompInterface di = new DecompInterface();
        di.toggleCCode(true);
        di.toggleSyntaxTree(true);
        di.openProgram(currentProgram);

        FunctionManager fm = currentProgram.getFunctionManager();
        int matched = 0;
        for (String raw : specs.split("[,+]")) {
            String spec = raw.trim();
            if (spec.isEmpty()) {
                continue;
            }
            if (spec.startsWith("0x") || spec.startsWith("0X")) {
                Address a = toAddr(spec);
                Function f = fm.getFunctionContaining(a);
                if (f == null) {
                    disassemble(a);
                    f = fm.getFunctionAt(a);
                    if (f == null) {
                        f = createFunction(a, null);
                    }
                }
                if (f == null) {
                    out.println("==== " + spec + "  // no containing function");
                    out.println();
                } else {
                    dump(out, di, f, timeout);
                    matched++;
                }
            } else {
                boolean exact = spec.startsWith("=");
                String needle = exact ? spec.substring(1) : spec;
                for (Function f : fm.getFunctions(true)) {
                    String name = f.getName();
                    boolean hit = exact ? name.equals(needle) : name.contains(needle);
                    if (hit) {
                        dump(out, di, f, timeout);
                        matched++;
                    }
                }
            }
        }
        out.println("// matched=" + matched);
        out.flush();
        out.close();
        di.dispose();
        println("DumpDecomp: matched=" + matched + " -> " + outPath);
    }
}
