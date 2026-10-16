// Ghidra headless script: list references to defined strings that contain a substring.
// Usage: -postScript FindStringRefs.java <outPath> <needle[+needle...]>
// Output lines: string address, string, then "  ref <from address> in <function entry> <function name>".
// @category REA
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Data;
import ghidra.program.model.listing.DataIterator;
import ghidra.program.model.listing.Function;
import ghidra.program.model.symbol.Reference;
import java.io.FileWriter;
import java.io.PrintWriter;

public class FindStringRefs extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        String outPath = args[0];
        String[] needles = args[1].split("[+]");
        PrintWriter out = new PrintWriter(new FileWriter(outPath));
        DataIterator it = currentProgram.getListing().getDefinedData(true);
        while (it.hasNext()) {
            Data d = it.next();
            Object v = d.getValue();
            if (!(v instanceof String)) {
                continue;
            }
            String s = (String) v;
            boolean hit = false;
            for (String n : needles) {
                if (!n.isEmpty() && s.contains(n)) {
                    hit = true;
                }
            }
            if (!hit) {
                continue;
            }
            out.println(d.getAddress() + "  \"" + s + "\"");
            for (Reference r : getReferencesTo(d.getAddress())) {
                Function f = currentProgram.getFunctionManager().getFunctionContaining(r.getFromAddress());
                out.println("  ref " + r.getFromAddress() + " in "
                        + (f == null ? "(no function)" : f.getEntryPoint() + " " + f.getName()));
            }
        }
        out.flush();
        out.close();
    }
}
