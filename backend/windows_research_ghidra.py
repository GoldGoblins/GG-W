"""Offline Ghidra JSON bridge: no localhost server or network exemption."""
from __future__ import annotations

from pathlib import Path

SCRIPT = r'''// Trusted GG static-analysis adapter. Selected programs are never executed.
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.mem.MemoryBlock;
import ghidra.program.model.symbol.Reference;
import ghidra.program.model.symbol.ReferenceIterator;
import com.google.gson.Gson;
import java.util.*;
import java.nio.file.*;
import java.nio.charset.StandardCharsets;

public class GGResearchReport extends GhidraScript {
    private Map<String,Object> procedure(Function f) {
        Map<String,Object> value = new LinkedHashMap<>();
        value.put("name", f.getName());
        value.put("address", f.getEntryPoint().toString());
        value.put("signature", f.getSignature().getPrototypeString());
        List<Object> ranges = new ArrayList<>();
        AddressRangeIterator it = f.getBody().getAddressRanges();
        while (it.hasNext() && ranges.size() < 64) {
            AddressRange span = it.next();
            ranges.add(Map.of("start",span.getMinAddress().toString(),"end",span.getMaxAddress().toString()));
        }
        value.put("body", Map.of("available",!f.getBody().isEmpty(),"ranges",ranges));
        return value;
    }

    private Function selected(String query) throws Exception {
        List<Function> matches = getGlobalFunctions(query);
        if (matches.size() == 1) return matches.get(0);
        if (matches.size() > 1) throw new IllegalArgumentException("AMBIGUOUS_FUNCTION_USE_ADDRESS");
        Address address = currentProgram.getAddressFactory().getAddress(query);
        Function f = address == null ? null : getFunctionContaining(address);
        if (f == null) throw new IllegalArgumentException("FUNCTION_NOT_FOUND");
        return f;
    }

    private List<Object> callers(Function f) {
        LinkedHashMap<String,Object> values = new LinkedHashMap<>();
        ReferenceIterator references = currentProgram.getReferenceManager().getReferencesTo(f.getEntryPoint());
        while (references.hasNext() && values.size() < 128) {
            Function caller = getFunctionContaining(references.next().getFromAddress());
            if (caller != null) values.put(caller.getEntryPoint().toString(),procedure(caller));
        }
        return new ArrayList<>(values.values());
    }

    protected void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length != 3) throw new IllegalArgumentException("GG_REPORT_ARGUMENTS");
        String operation=args[0], query=args[1];
        Map<String,Object> output = new LinkedHashMap<>();
        output.put("operation",operation);
        output.put("provider",Map.of("name","Ghidra","version","12.1.4","transport","offline-file"));
        String format=currentProgram.getExecutableFormat();
        String kind=format.toLowerCase().contains("portable") ? "pe" :
            (format.toLowerCase().contains("elf") ? "elf" : format);
        output.put("subject",Map.of("format",kind,"name",currentProgram.getName()));
        try {
            Object normalized;
            if (operation.equals("analyze")) {
                List<Object> segments = new ArrayList<>();
                for (MemoryBlock b: currentProgram.getMemory().getBlocks()) {
                    if (segments.size() >= 128) break;
                    segments.add(Map.of("name",b.getName(),"start",b.getStart().toString(),
                        "end",b.getEnd().toString(),"read",b.isRead(),"write",b.isWrite(),"execute",b.isExecute()));
                }
                List<Object> functions = new ArrayList<>();
                FunctionIterator it=currentProgram.getFunctionManager().getFunctions(true);
                while (it.hasNext() && functions.size()<128) functions.add(procedure(it.next()));
                normalized=Map.of("format",kind,"procedure_count",currentProgram.getFunctionManager().getFunctionCount(),
                    "procedures",functions,"segments",segments);
            } else if (operation.equals("search")) {
                List<Object> matches = new ArrayList<>();
                FunctionIterator it=currentProgram.getFunctionManager().getFunctions(true);
                while (it.hasNext() && matches.size()<128) {
                    Function f=it.next();
                    if (f.getName().toLowerCase().contains(query.toLowerCase())) matches.add(procedure(f));
                }
                normalized=matches;
            } else if (operation.equals("xrefs")) {
                List<Function> named=getGlobalFunctions(query);
                if (named.size()>1) throw new IllegalArgumentException("AMBIGUOUS_FUNCTION_USE_ADDRESS");
                Address address=named.size()==1 ? named.get(0).getEntryPoint()
                    : currentProgram.getAddressFactory().getAddress(query);
                if (address==null) address=selected(query).getEntryPoint();
                List<Object> references=new ArrayList<>();
                ReferenceIterator it=currentProgram.getReferenceManager().getReferencesTo(address);
                while (it.hasNext() && references.size()<128) {
                    Address from=it.next().getFromAddress();
                    if (from.isMemoryAddress()) references.add(from.toString());
                }
                normalized=references;
            } else if (operation.equals("decompile")) {
                DecompInterface decompiler=new DecompInterface();
                try {
                    if (!decompiler.openProgram(currentProgram)) throw new IllegalStateException("DECOMPILER_OPEN_FAILED");
                    DecompileResults result=decompiler.decompileFunction(selected(query),60,monitor);
                    if (!result.decompileCompleted() || result.getDecompiledFunction()==null)
                        throw new IllegalStateException("DECOMPILATION_FAILED");
                    String code=result.getDecompiledFunction().getC();
                    if (code.length()>128*1024) throw new IllegalStateException("PSEUDOCODE_LIMIT");
                    normalized=code;
                } finally { decompiler.dispose(); }
            } else if (operation.equals("function")) {
                Function f=selected(query);
                List<Object> callees=new ArrayList<>();
                for (Function called:f.getCalledFunctions(monitor)) {
                    if (callees.size()>=128) break;
                    callees.add(procedure(called));
                }
                Map<String,Object> result=new LinkedHashMap<>();
                result.put("procedure",procedure(f)); result.put("callers",callers(f)); result.put("callees",callees);
                normalized=result;
            } else throw new IllegalArgumentException("UNSUPPORTED_OPERATION");
            output.put("normalized_result",normalized);
            output.put("limitations",List.of("Static analysis only; selected target code is never executed.",
                "Collections are bounded to 128 records; pseudocode requires independent validation."));
        } catch (Exception e) {
            output.put("ok",false); output.put("error",e.getMessage()==null?e.getClass().getSimpleName():e.getMessage());
        }
        Files.writeString(Path.of(args[2]),new Gson().toJson(output),StandardCharsets.UTF_8);
    }
}
'''


def command(tools: Path, scratch: Path, target: Path, operation: str, query: str):
    scripts = tools / 'gg-scripts'
    scripts.mkdir(exist_ok=True)
    script = scripts / 'GGResearchReport.java'
    if not script.is_file() or script.read_text(encoding='utf-8') != SCRIPT:
        script.write_text(SCRIPT, encoding='utf-8', newline='\n')
    project = scratch / 'home/projects'
    project.mkdir(parents=True, exist_ok=True)
    report = scratch / 'tmp/ghidra-result.json'
    argv = [str(tools / 'jdk/bin/java.exe'), '-Xmx512m', '-XX:ActiveProcessorCount=2',
        '-Djava.awt.headless=true', '-Djava.system.class.loader=ghidra.GhidraClassLoader',
        '-Dfile.encoding=UTF-8', '-cp', str(tools / 'ghidra/Ghidra/Framework/Utility/lib/Utility.jar'),
        'ghidra.Ghidra', 'ghidra.app.util.headless.AnalyzeHeadless', str(project), 'gg-analysis',
        '-import', str(target), '-deleteProject', '-analysisTimeoutPerFile', '180',
        '-scriptPath', str(scripts), '-postScript', 'GGResearchReport.java', operation, query or '__GG_NO_QUERY__', str(report)]
    return argv, report
