/* SPDX-License-Identifier: GPL-3.0-or-later. Host test, never installed on the unit. */
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.List;
import org.objectweb.asm.ClassReader;
import org.objectweb.asm.Opcodes;
import org.objectweb.asm.tree.AbstractInsnNode;
import org.objectweb.asm.tree.ClassNode;
import org.objectweb.asm.tree.FieldNode;
import org.objectweb.asm.tree.MethodInsnNode;
import org.objectweb.asm.tree.MethodNode;
import org.objectweb.asm.tree.TryCatchBlockNode;
import org.objectweb.asm.tree.FieldInsnNode;
import org.objectweb.asm.tree.IincInsnNode;
import org.objectweb.asm.tree.IntInsnNode;
import org.objectweb.asm.tree.JumpInsnNode;
import org.objectweb.asm.tree.LabelNode;
import org.objectweb.asm.tree.LdcInsnNode;
import org.objectweb.asm.tree.LookupSwitchInsnNode;
import org.objectweb.asm.tree.MultiANewArrayInsnNode;
import org.objectweb.asm.tree.TableSwitchInsnNode;
import org.objectweb.asm.tree.TypeInsnNode;
import org.objectweb.asm.tree.VarInsnNode;

/**
 * The patched AbstractViewHandler is the factory class plus the five guarded calls, nothing else:
 * same fields, interfaces, access flags and methods; every method without a hook has exactly the factory bytecode;
 * in the five hooked methods the factory instructions appear in order and everything added is only the guard
 * (loads/stores of fresh locals, GOTO, POP, labels) around one MenuHook call, with one Throwable handler each.
 *
 * Usage: TestMenuHookPatch <stockClassesDir> <patchedClassesDir>
 */
public final class TestMenuHookPatch {
    static int checks;

    public static void main(String[] args) throws Exception {
        String name = PatchMenuHook.TARGET + ".class";
        ClassNode stock = read(Paths.get(args[0]).resolve(name));
        ClassNode patched = read(Paths.get(args[1]).resolve(name));
        check(patched.version == 46, "version 46");
        check(patched.access == stock.access, "class access");
        check(patched.superName.equals(stock.superName), "super class");
        check(patched.interfaces.equals(stock.interfaces), "interfaces");
        check(patched.fields.size() == stock.fields.size(), "field count");
        for (int i = 0; i < stock.fields.size(); i++) {
            FieldNode a = stock.fields.get(i);
            FieldNode b = patched.fields.get(i);
            check(a.name.equals(b.name) && a.desc.equals(b.desc) && a.access == b.access, "field " + a.name);
        }
        check(patched.methods.size() == stock.methods.size(), "method count");
        int hooked = 0;
        for (int i = 0; i < stock.methods.size(); i++) {
            MethodNode a = stock.methods.get(i);
            MethodNode b = patched.methods.get(i);
            check(a.name.equals(b.name) && a.desc.equals(b.desc) && a.access == b.access, "method " + a.name);
            String hook = hookOf(a);
            if (hook == null) {
                check(text(a).equals(text(b)), "unchanged bytecode " + a.name + a.desc);
                check(a.tryCatchBlocks.size() == b.tryCatchBlocks.size(), "unchanged handlers " + a.name);
                continue;
            }
            hooked++;
            checkHooked(a, b, hook);
        }
        check(hooked == 5, "five hooked methods");
        System.out.println("MENU_HOOK_PATCH_PASS " + checks);
    }

    static String hookOf(MethodNode m) {
        if (m.desc.equals("()V")) {
            for (String[] hook : PatchMenuHook.RETURN_HOOKS) {
                if (hook[0].equals(m.name)) {
                    return hook[1];
                }
            }
        }
        for (String[] hook : PatchMenuHook.START_HOOKS) {
            if (hook[0].equals(m.name) && hook[1].equals(m.desc)) {
                return "start:" + hook[2];
            }
        }
        if (m.name.equals("fatalError") && m.desc.equals("(Ljava/lang/RuntimeException;)V")) {
            return "start:failure";
        }
        return null;
    }

    static void checkHooked(MethodNode stock, MethodNode patched, String spec) {
        boolean atStart = spec.startsWith("start:");
        String hook = atStart ? spec.substring(6) : spec;
        List<AbstractInsnNode> a = real(stock);
        List<AbstractInsnNode> b = real(patched);
        int calls = 0;
        int at = -1;
        // factory instructions matched in order: from the end for a hook at the start (the guard's ALOAD 0 spill
        // must not take the place of the factory's first ALOAD 0), from the start for a hook before RETURN
        int[] matchPos = new int[a.size()];
        boolean[] added = new boolean[b.size()];
        int j;
        if (atStart) {
            j = a.size() - 1;
            for (int k = b.size() - 1; k >= 0; k--) {
                if (j >= 0 && same(a.get(j), b.get(k))) matchPos[j--] = k; else added[k] = true;
            }
            j = j < 0 ? a.size() : -1;
        } else {
            j = 0;
            for (int k = 0; k < b.size(); k++) {
                if (j < a.size() && same(a.get(j), b.get(k))) matchPos[j++] = k; else added[k] = true;
            }
        }
        for (int k = 0; k < b.size(); k++) {
            AbstractInsnNode insn = b.get(k);
            if (!added[k]) {
                continue;
            }
            if (insn instanceof MethodInsnNode) {
                at = k;
            }
            int op = insn.getOpcode();
            if (insn instanceof MethodInsnNode) {
                MethodInsnNode call = (MethodInsnNode) insn;
                check(call.getOpcode() == Opcodes.INVOKESTATIC && call.owner.equals(PatchMenuHook.HELPER)
                        && call.name.equals(hook), "only the MenuHook." + hook + " call added in " + stock.name);
                calls++;
                continue;
            }
            boolean guard = op == Opcodes.ALOAD || op == Opcodes.ASTORE || op == Opcodes.GOTO || op == Opcodes.POP;
            check(guard, "only guard instructions added in " + stock.name + " (opcode " + op + ")");
        }
        check(j == a.size(), "all factory instructions kept in order in " + stock.name);
        check(calls == 1, "one call in " + stock.name);
        check(patched.tryCatchBlocks.size() == stock.tryCatchBlocks.size() + 1, "one handler added in " + stock.name);
        TryCatchBlockNode first = patched.tryCatchBlocks.get(0);
        check("java/lang/Throwable".equals(first.type), "guard catches Throwable in " + stock.name);
        for (int i = 0; i < stock.tryCatchBlocks.size(); i++) {
            String sType = stock.tryCatchBlocks.get(i).type;
            String pType = patched.tryCatchBlocks.get(i + 1).type;
            check(sType == null ? pType == null : sType.equals(pType), "factory handler kept in " + stock.name);
        }
        if (atStart) {
            check(at < matchPos[0], hook + " before the first factory instruction of " + stock.name);
        } else {
            int last = a.size() - 1;
            check(matchPos[last - 1] < at && at < matchPos[last] && matchPos[last] == b.size() - 1
                    && b.get(b.size() - 1).getOpcode() == Opcodes.RETURN,
                    hook + " between the factory body and its final RETURN in " + stock.name);
        }
        // factory handlers keep their ranges: start, end and handler map to the same factory instructions
        for (int i = 0; i < stock.tryCatchBlocks.size(); i++) {
            TryCatchBlockNode x = stock.tryCatchBlocks.get(i);
            TryCatchBlockNode y = patched.tryCatchBlocks.get(i + 1);
            check(b.indexOf(first(y.start)) == matchPos[a.indexOf(first(x.start))]
                    && b.indexOf(first(y.end)) == matchPos[a.indexOf(first(x.end))]
                    && b.indexOf(first(y.handler)) == matchPos[a.indexOf(first(x.handler))],
                    "factory handler range kept in " + stock.name);
        }
    }

    static AbstractInsnNode first(LabelNode label) {
        for (AbstractInsnNode n = label; n != null; n = n.getNext()) {
            if (n.getOpcode() >= 0) return n;
        }
        throw new IllegalStateException("label without code");
    }

    static List<AbstractInsnNode> real(MethodNode m) {
        List<AbstractInsnNode> out = new ArrayList<AbstractInsnNode>();
        for (AbstractInsnNode insn : m.instructions) {
            if (insn.getOpcode() >= 0) {
                out.add(insn);
            }
        }
        // the converted JXE pads method ends with NOPs; they stay (compared above), but are not the "end"
        while (!out.isEmpty() && out.get(out.size() - 1).getOpcode() == Opcodes.NOP) {
            out.remove(out.size() - 1);
        }
        return out;
    }

    /** Operands without jump targets (hooked methods: the guard moves label positions). */
    static boolean same(AbstractInsnNode a, AbstractInsnNode b) {
        return a.getOpcode() == b.getOpcode() && one(null, a).equals(one(null, b));
    }

    static String one(MethodNode m, AbstractInsnNode insn) {
        StringBuilder t = new StringBuilder().append(insn.getOpcode()).append(' ');
        if (insn instanceof VarInsnNode) t.append(((VarInsnNode) insn).var);
        else if (insn instanceof IntInsnNode) t.append(((IntInsnNode) insn).operand);
        else if (insn instanceof IincInsnNode) t.append(((IincInsnNode) insn).var).append(',').append(((IincInsnNode) insn).incr);
        else if (insn instanceof TypeInsnNode) t.append(((TypeInsnNode) insn).desc);
        else if (insn instanceof MultiANewArrayInsnNode) t.append(((MultiANewArrayInsnNode) insn).desc).append(((MultiANewArrayInsnNode) insn).dims);
        else if (insn instanceof LdcInsnNode) t.append(((LdcInsnNode) insn).cst.getClass().getName()).append(':').append(((LdcInsnNode) insn).cst);
        else if (insn instanceof FieldInsnNode) { FieldInsnNode f = (FieldInsnNode) insn; t.append(f.owner).append('.').append(f.name).append(f.desc); }
        else if (insn instanceof MethodInsnNode) { MethodInsnNode c = (MethodInsnNode) insn; t.append(c.owner).append('.').append(c.name).append(c.desc).append(c.itf); }
        else if (insn instanceof JumpInsnNode) t.append(target(m, ((JumpInsnNode) insn).label));
        else if (insn instanceof TableSwitchInsnNode) { TableSwitchInsnNode s = (TableSwitchInsnNode) insn; t.append(s.min).append('-').append(s.max).append(' ').append(target(m, s.dflt)); for (LabelNode l : s.labels) t.append(',').append(target(m, l)); }
        else if (insn instanceof LookupSwitchInsnNode) { LookupSwitchInsnNode s = (LookupSwitchInsnNode) insn; t.append(s.keys).append(' ').append(target(m, s.dflt)); for (LabelNode l : s.labels) t.append(',').append(target(m, l)); }
        return t.toString();
    }

    /** Index of the first real instruction at or after the label (null method: not compared). */
    static int target(MethodNode m, LabelNode label) {
        if (m == null) return -1;
        int index = 0;
        boolean seen = false;
        for (AbstractInsnNode insn : m.instructions) {
            if (insn == label) seen = true;
            if (insn.getOpcode() >= 0) {
                if (seen) return index;
                index++;
            }
        }
        return index;
    }

    static String text(MethodNode m) {
        StringBuilder t = new StringBuilder();
        for (AbstractInsnNode insn : m.instructions) {
            if (insn.getOpcode() >= 0) t.append(one(m, insn)).append('\n');
        }
        for (TryCatchBlockNode h : m.tryCatchBlocks) {
            t.append("try ").append(target(m, h.start)).append(' ').append(target(m, h.end)).append(' ')
                    .append(target(m, h.handler)).append(' ').append(h.type).append('\n');
        }
        return t.toString();
    }

    static ClassNode read(Path path) throws Exception {
        ClassNode node = new ClassNode();
        new ClassReader(Files.readAllBytes(path)).accept(node, ClassReader.SKIP_FRAMES | ClassReader.SKIP_DEBUG);
        return node;
    }

    static void check(boolean ok, String what) {
        checks++;
        if (!ok) {
            throw new IllegalStateException("FAIL " + what);
        }
    }
}
