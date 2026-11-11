/* SPDX-License-Identifier: GPL-3.0-or-later. Host build tool, never installed on the unit. */
import org.objectweb.asm.*;
import org.objectweb.asm.tree.*;
import org.objectweb.asm.tree.analysis.AnalyzerException;
import java.nio.file.*;

/**
 * A166 (AA 1.1 research): the AID view signals into com/pmcp/kv/KombiView, each at the entry of a stock method and
 * wrapped by Guard.wrapCall (buildtools/Guard.java), so a helper J9 cannot load or run never reaches the stock code:
 *   mostkombi ChangeDataRate.dsiKOMOGfxStreamSinkUpdateDataRate(II)V  -> KombiView.onDataRate(rate, valid)
 *   navigation MapViewerKombiNotifierModel.notifyKombiMapVisible()V   -> KombiView.onMapVisibility(1)
 *   navigation MapViewerKombiNotifierModel.notifyKombiMapInvisible()V -> KombiView.onMapVisibility(0)
 *   navsd ActiveRgType.setGetProperty(BAPEntity, PropertyListener)V   -> KombiView.onRgTypeSetGet(entity)
 * The stock method bodies are asserted by their first instructions; anything else aborts the build.
 *
 * usage: java PatchKombiView <stockClassesDir> <outDir>
 */
public final class PatchKombiView {
    static final String KV = "com/pmcp/kv/KombiView";
    static final String CDR = "de/vw/mib/asl/internal/mostkombi/streamsink/usecases/ChangeDataRate";
    static final String MVN = "de/vw/mib/asl/internal/navigation/map/kombi/MapViewerKombiNotifierModel";
    static final String ART = "de/vw/mib/bap/mqbab2/navsd/functions/ActiveRgType";
    static Path in, out;

    static void expect(boolean ok, String what) {
        if (!ok) throw new IllegalStateException("PatchKombiView: " + what);
    }

    public static void main(String[] a) throws Exception {
        in = Paths.get(a[0]); out = Paths.get(a[1]);
        {
            ClassNode cn = read(CDR);
            MethodNode m = method(cn, "dsiKOMOGfxStreamSinkUpdateDataRate", "(II)V");
            AbstractInsnNode f = first(m);
            expect(f.getOpcode() == Opcodes.ALOAD && isCall(f.getNext(), Opcodes.INVOKESPECIAL, CDR, "getStreamSinkDataRate", "()I"),
                    "ChangeDataRate starts with getStreamSinkDataRate()");
            entry(cn, m, new int[]{Opcodes.ILOAD, 1, Opcodes.ILOAD, 2}, "onDataRate", "(II)V");
            write(cn);
        }
        {
            ClassNode cn = read(MVN);
            for (int v = 0; v <= 1; v++) {
                MethodNode m = method(cn, v == 1 ? "notifyKombiMapVisible" : "notifyKombiMapInvisible", "()V");
                int ldc = 0, write = 0;
                for (AbstractInsnNode n : m.instructions) {
                    if (n instanceof LdcInsnNode && Integer.valueOf(1110045).equals(((LdcInsnNode) n).cst)) ldc++;
                    if (isCall(n, Opcodes.INVOKESTATIC, "de/vw/mib/asl/framework/internal/framework/AbstractASLHsmTarget",
                            "writeIntegerToDatapool", "(II)V")) write++;
                }
                expect(ldc == 1 && write == 1, m.name + " writes datapool 1110045 once");
                entry(cn, m, new int[]{v == 1 ? Opcodes.ICONST_1 : Opcodes.ICONST_0, -1}, "onMapVisibility", "(I)V");
            }
            write(cn);
        }
        {
            ClassNode cn = read(ART);
            MethodNode m = method(cn, "setGetProperty",
                    "(Lde/vw/mib/bap/datatypes/BAPEntity;Lde/vw/mib/bap/functions/PropertyListener;)V");
            expect((m.access & Opcodes.ACC_STATIC) == 0, "ActiveRgType.setGetProperty is an instance method");
            entry(cn, m, new int[]{Opcodes.ALOAD, 1}, "onRgTypeSetGet", "(Ljava/lang/Object;)V");
            write(cn);
        }
        downgradeHelper();
        System.out.println("OK kombi view");
    }

    /** The helper, compiled with --release 8 into outDir, to class version 46 without frames; J9 CDC 1.1 rules. */
    static void downgradeHelper() throws Exception {
        Path p = out.resolve(KV + ".class");
        ClassNode cn = new ClassNode();
        new ClassReader(Files.readAllBytes(p)).accept(cn, ClassReader.SKIP_FRAMES);
        cn.version = 46;
        for (MethodNode m : cn.methods) {
            m.localVariables = null;
            for (AbstractInsnNode n : m.instructions) {
                expect(!(n instanceof MethodInsnNode && ((MethodInsnNode) n).owner.startsWith("java/lang/StringBuilder")), "StringBuilder in helper");
                expect(!(n instanceof InvokeDynamicInsnNode), "indy in helper");
                expect(!(n instanceof LdcInsnNode && ((LdcInsnNode) n).cst instanceof Type), "class literal in helper");
            }
        }
        ClassWriter cw = new ClassWriter(ClassWriter.COMPUTE_MAXS);
        cn.accept(cw);
        Files.write(p, cw.toByteArray());
        System.out.println("helper " + KV + " version 46");
    }

    /** At the method entry: the loads (opcode, var; var -1 = no operand), then the guarded static call. */
    static void entry(ClassNode cn, MethodNode m, int[] loads, String name, String desc) throws AnalyzerException {
        InsnList p = new InsnList();
        for (int i = 0; i < loads.length; i += 2)
            p.add(loads[i + 1] < 0 ? new InsnNode(loads[i]) : new VarInsnNode(loads[i], loads[i + 1]));
        MethodInsnNode call = new MethodInsnNode(Opcodes.INVOKESTATIC, KV, name, desc, false);
        p.add(call);
        m.instructions.insert(p);
        Guard.wrapCall(cn.name, m, call, Guard.popArgsReturnZero(call.desc));
    }

    static AbstractInsnNode first(MethodNode m) {
        AbstractInsnNode n = m.instructions.getFirst();
        while (n != null && n.getOpcode() < 0) n = n.getNext();
        return n;
    }

    static ClassNode read(String name) throws Exception {
        ClassNode cn = new ClassNode();
        new ClassReader(Files.readAllBytes(in.resolve(name + ".class"))).accept(cn, ClassReader.SKIP_FRAMES);
        expect(cn.version == 46 || cn.version == 49, cn.name + " version " + cn.version);
        for (MethodNode m : cn.methods)
            for (AbstractInsnNode n : m.instructions)
                if (n instanceof LdcInsnNode) expect(!(((LdcInsnNode) n).cst instanceof Type), cn.name + "." + m.name + " class literal");
        cn.version = 46;
        return cn;
    }

    static MethodNode method(ClassNode cn, String name, String desc) {
        MethodNode r = null;
        for (MethodNode m : cn.methods)
            if (m.name.equals(name) && m.desc.equals(desc)) { expect(r == null, "duplicate " + name); r = m; }
        expect(r != null, "method " + cn.name + "." + name + desc);
        return r;
    }

    static boolean isCall(AbstractInsnNode n, int op, String owner, String name, String desc) {
        if (!(n instanceof MethodInsnNode) || n.getOpcode() != op) return false;
        MethodInsnNode m = (MethodInsnNode) n;
        return m.owner.equals(owner) && m.name.equals(name) && m.desc.equals(desc);
    }

    static void write(ClassNode cn) throws Exception {
        Guard.checkAllGuarded(cn, "com/pmcp/");
        ClassWriter cw = new ClassWriter(ClassWriter.COMPUTE_MAXS);
        cn.accept(cw);
        Path p = out.resolve(cn.name + ".class");
        Files.createDirectories(p.getParent());
        Files.write(p, cw.toByteArray());
        System.out.println("patched " + cn.name);
    }
}
