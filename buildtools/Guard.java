/* SPDX-License-Identifier: GPL-3.0-or-later. Host build tool, never installed on the unit. */
import org.objectweb.asm.*;
import org.objectweb.asm.tree.*;
import org.objectweb.asm.tree.analysis.*;
import java.util.*;

/**
 * Guards every call from a stock (firmware) method into our helper classes, so that nothing our code or the VM throws
 * there can reach the HMI: not only exceptions inside the helper (the helpers catch those themselves) but also what J9
 * raises at the call site while resolving the helper (NoClassDefFoundError, VerifyError, ExceptionInInitializerError,
 * LinkageError). Code review 2, finding 1.
 *
 * For a call site with the operand stack S = below + args, wrapCall emits (stack values spilled to fresh locals, as the
 * JVM clears the stack when it enters a handler):
 *
 *     store S to fresh locals
 *   start:
 *     load S ; call helper              (the original call)
 *   end:
 *     goto after
 *   handler:                            (catch java/lang/Throwable, first in the exception table = innermost)
 *     pop ; load S ; fallback           (fallback consumes args, pushes the call's return value)
 *   after:
 *
 * Class files are version 46 (no StackMapTable), so no frames are written. The build analyses the method afterwards
 * (Analyzer + BasicVerifier) and the host tests run the classes under -Xverify:all.
 */
public final class Guard {
    private Guard() {
    }

    static void expect(boolean ok, String what) {
        if (!ok) throw new IllegalStateException("guard: " + what);
    }

    /** Wraps the given call instruction of m. The fallback must turn the call's arguments into its return value. */
    public static void wrapCall(String owner, MethodNode m, MethodInsnNode call, InsnList fallback) throws AnalyzerException {
        expect(call.getOpcode() == Opcodes.INVOKESTATIC, "only invokestatic is guarded: " + call.owner + "." + call.name);
        expect(m.instructions.contains(call), "call not in method " + m.name);
        Frame<BasicValue> f = frames(owner, m)[m.instructions.indexOf(call)];
        expect(f != null, "unreachable call " + call.name + " in " + m.name);
        int depth = f.getStackSize();
        int nargs = Type.getArgumentTypes(call.desc).length;
        expect(depth >= nargs, "stack shorter than arguments at " + call.name);

        int[] slot = new int[depth];
        int[] load = new int[depth];
        int[] store = new int[depth];
        int next = m.maxLocals;
        for (int i = 0; i < depth; i++) {
            BasicValue v = f.getStack(i);
            if (v == BasicValue.INT_VALUE) { load[i] = Opcodes.ILOAD; store[i] = Opcodes.ISTORE; }
            else if (v == BasicValue.FLOAT_VALUE) { load[i] = Opcodes.FLOAD; store[i] = Opcodes.FSTORE; }
            else if (v == BasicValue.LONG_VALUE) { load[i] = Opcodes.LLOAD; store[i] = Opcodes.LSTORE; }
            else if (v == BasicValue.DOUBLE_VALUE) { load[i] = Opcodes.DLOAD; store[i] = Opcodes.DSTORE; }
            else if (v == BasicValue.REFERENCE_VALUE) { load[i] = Opcodes.ALOAD; store[i] = Opcodes.ASTORE; }
            else throw new IllegalStateException("guard: stack value " + v + " at " + call.name + " (returnAddress/uninitialized)");
            slot[i] = next;
            next += v.getSize();
        }
        m.maxLocals = next;

        InsnList pre = new InsnList();
        for (int i = depth - 1; i >= 0; i--) pre.add(new VarInsnNode(store[i], slot[i]));
        LabelNode start = new LabelNode(), end = new LabelNode(), handler = new LabelNode(), after = new LabelNode();
        pre.add(start);
        for (int i = 0; i < depth; i++) pre.add(new VarInsnNode(load[i], slot[i]));
        m.instructions.insertBefore(call, pre);

        InsnList post = new InsnList();
        post.add(end);
        post.add(new JumpInsnNode(Opcodes.GOTO, after));
        post.add(handler);
        post.add(new InsnNode(Opcodes.POP));
        for (int i = 0; i < depth; i++) post.add(new VarInsnNode(load[i], slot[i]));
        post.add(fallback);
        post.add(after);
        m.instructions.insert(call, post);
        m.tryCatchBlocks.add(0, new TryCatchBlockNode(start, end, handler, "java/lang/Throwable"));
        frames(owner, m); // the patched method must still analyse
    }

    /** Every invokestatic into one of the helper packages (internal-name prefixes) must be a guarded call. */
    public static void checkAllGuarded(ClassNode cn, String... helperPrefixes) {
        int calls = 0;
        for (MethodNode m : cn.methods) {
            for (AbstractInsnNode n : m.instructions) {
                if (!(n instanceof MethodInsnNode)) continue;
                MethodInsnNode mi = (MethodInsnNode) n;
                boolean ours = false;
                for (String p : helperPrefixes) ours |= mi.owner.startsWith(p);
                if (!ours) continue;
                calls++;
                expect(mi.getOpcode() == Opcodes.INVOKESTATIC, "non-static helper call " + mi.owner + "." + mi.name);
                expect(guarded(m, mi), "unguarded helper call " + cn.name + "." + m.name + " -> " + mi.owner + "." + mi.name);
            }
        }
        expect(calls > 0, "no helper calls in " + cn.name);
    }

    static boolean guarded(MethodNode m, MethodInsnNode call) {
        int at = m.instructions.indexOf(call);
        // our wrapper is the first exception-table entry covering the call, catches Throwable, and ends right after it
        for (TryCatchBlockNode t : m.tryCatchBlocks) {
            int s = m.instructions.indexOf(t.start), e = m.instructions.indexOf(t.end);
            if (at < s || at >= e) continue;
            return "java/lang/Throwable".equals(t.type) && t.end == call.getNext();
        }
        return false;
    }

    static Frame<BasicValue>[] frames(String owner, MethodNode m) throws AnalyzerException {
        int ms = m.maxStack, ml = m.maxLocals;
        m.maxStack = ms + 32;   // the writer recomputes both (COMPUTE_MAXS)
        try {
            return new Analyzer<BasicValue>(new BasicVerifier()).analyze(owner, m);
        } finally {
            m.maxStack = ms;
            m.maxLocals = ml;
        }
    }

    // ---- fallbacks ----------------------------------------------------------------------------------------------

    /** Pops the call's arguments and pushes a zero of its return type (void: nothing). */
    public static InsnList popArgsReturnZero(String desc) {
        InsnList l = new InsnList();
        Type[] args = Type.getArgumentTypes(desc);
        for (int i = args.length - 1; i >= 0; i--) l.add(new InsnNode(args[i].getSize() == 2 ? Opcodes.POP2 : Opcodes.POP));
        Type r = Type.getReturnType(desc);
        switch (r.getSort()) {
            case Type.VOID: break;
            case Type.BOOLEAN: case Type.BYTE: case Type.CHAR: case Type.SHORT: case Type.INT: l.add(new InsnNode(Opcodes.ICONST_0)); break;
            case Type.LONG: l.add(new InsnNode(Opcodes.LCONST_0)); break;
            case Type.FLOAT: l.add(new InsnNode(Opcodes.FCONST_0)); break;
            case Type.DOUBLE: l.add(new InsnNode(Opcodes.DCONST_0)); break;
            default: l.add(new InsnNode(Opcodes.ACONST_NULL));
        }
        return l;
    }
}
