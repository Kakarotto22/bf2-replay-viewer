// Ghidra headless script: list symbols whose name contains one of the needles.
// Usage: -postScript FindSymbols.java <outPath> <needle[+needle...]>
// @category REA
import ghidra.app.script.GhidraScript;
import ghidra.program.model.symbol.Symbol;
import ghidra.program.model.symbol.SymbolIterator;
import java.io.FileWriter;
import java.io.PrintWriter;

public class FindSymbols extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        String[] needles = args[1].split("[+]");
        PrintWriter out = new PrintWriter(new FileWriter(args[0]));
        SymbolIterator it = currentProgram.getSymbolTable().getAllSymbols(true);
        while (it.hasNext()) {
            Symbol s = it.next();
            String name = s.getName(true);
            for (String n : needles) {
                if (!n.isEmpty() && name.contains(n)) {
                    out.println(s.getAddress() + "  " + s.getSymbolType() + "  " + name);
                    break;
                }
            }
        }
        out.flush();
        out.close();
    }
}
