/* SPDX-License-Identifier: GPL-3.0-or-later. Host build tool, never installed on the unit. */
import org.objectweb.asm.*;
import org.objectweb.asm.tree.*;
import org.objectweb.asm.tree.analysis.AnalyzerException;
import java.io.*;
import java.nio.file.*;

/**
 * Package D (track title / artist on the cluster): three hooks into the firmware's own classes.
 * Every hook asserts the exact stock pattern and its count; anything else aborts the build. Every call into our helper
 * is wrapped by Guard.wrapCall (buildtools/Guard.java): if J9 cannot load or run it, the stock path continues.
 *
 * usage: java PatchNp <stockClassesDir> <helperClassesDir> <outDir>
 */
public class PatchNp {
    static final int CLASS_VERSION = 46; // factory J9; the converter emits some stock classes as 49
    static final String NP = "com/pmcp/np/NowPlaying";
    static final String HSM = "de/vw/mib/asl/internal/carplay/target/HsmTarget";
    static final String CSI = "de/vw/mib/bap/mqbab2/audiosd/functions/CurrentStationInfo";
    static final String STATUS = "de/vw/mib/bap/mqbab2/generated/audiosd/serializer/CurrentStationInfo_Status";
    static Path in, helper, out;

    public static void main(String[] a) throws Exception {
        in = Paths.get(a[0]); helper = Paths.get(a[1]); out = Paths.get(a[2]);
        patchHsmTarget();
        patchCurrentStationInfo();
        for (String h : new String[] {NP, NP + "$1", "com/pmcp/np/NowPlayingListener"}) downgradeHelper(h);
        System.out.println("OK");
    }

    static void expect(boolean ok, String what) {
        if (!ok) throw new IllegalStateException("pattern mismatch: " + what);
    }

    static ClassNode read(Path dir, String name) throws IOException {
        ClassNode cn = new ClassNode();
        new ClassReader(Files.readAllBytes(dir.resolve(name + ".class"))).accept(cn, ClassReader.SKIP_FRAMES);
        return cn;
    }

    /** Stock classes come as 46 or 49; 49 is lowered only if no 49-only construct (class literal ldc) is used. */
    static void toFactoryVersion(ClassNode cn) {
        expect(cn.version == 46 || cn.version == 49, cn.name + " version " + cn.version);
        for (MethodNode m : cn.methods)
            for (AbstractInsnNode n : m.instructions)
                if (n instanceof LdcInsnNode) expect(!(((LdcInsnNode) n).cst instanceof Type), cn.name + "." + m.name + " uses a class literal");
        cn.version = CLASS_VERSION;
    }

    static void write(ClassNode cn) throws IOException {
        if (cn.version != CLASS_VERSION) throw new IllegalStateException(cn.name + " version " + cn.version);
        if (!cn.name.startsWith("com/pmcp/")) Guard.checkAllGuarded(cn, "com/pmcp/");
        ClassWriter cw = new ClassWriter(ClassWriter.COMPUTE_MAXS);
        cn.accept(cw);
        Path p = out.resolve(cn.name + ".class");
        Files.createDirectories(p.getParent());
        Files.write(p, cw.toByteArray());
        System.out.println("patched " + cn.name);
    }

    static MethodNode method(ClassNode cn, String name, String desc) {
        MethodNode r = null;
        for (MethodNode m : cn.methods)
            if (m.name.equals(name) && m.desc.equals(desc)) { expect(r == null, "duplicate " + name); r = m; }
        expect(r != null, "method " + cn.name + "." + name + desc);
        return r;
    }

    static AbstractInsnNode real(AbstractInsnNode n) {
        while (n != null && n.getOpcode() < 0) n = n.getNext();
        return n;
    }

    static boolean isCall(AbstractInsnNode n, int op, String owner, String name, String desc) {
        if (!(n instanceof MethodInsnNode) || n.getOpcode() != op) return false;
        MethodInsnNode m = (MethodInsnNode) n;
        return m.owner.equals(owner) && m.name.equals(name) && m.desc.equals(desc);
    }

    static void downgradeHelper(String name) throws IOException {
        ClassNode cn = read(helper, name);
        cn.version = CLASS_VERSION;
        for (MethodNode m : cn.methods) {
            m.localVariables = null;
            for (AbstractInsnNode n : m.instructions) {
                if (n instanceof MethodInsnNode && ((MethodInsnNode) n).owner.startsWith("java/lang/StringBuilder"))
                    throw new IllegalStateException("StringBuilder in helper " + name);
                if (n instanceof InvokeDynamicInsnNode) throw new IllegalStateException("indy in helper " + name);
                if (n instanceof LdcInsnNode && ((LdcInsnNode) n).cst instanceof Type)
                    throw new IllegalStateException("class literal in helper " + name);
            }
        }
        write(cn);
    }

    // ------------------------------------------------- 1. HsmTarget.initializeDSI
    // After the stock dsiCarplay.setNotification(DSI_CARPLAY_ATTR, dsiCarPlayListener):
    //     NowPlaying.attach(this.dsiCarplay);
    static void patchHsmTarget() throws IOException, AnalyzerException {
        ClassNode cn = read(in, HSM);
        toFactoryVersion(cn);
        MethodNode m = method(cn, "initializeDSI", "()V");
        int hits = 0;
        for (AbstractInsnNode n = m.instructions.getFirst(); n != null; n = n.getNext()) {
            if (isCall(n, Opcodes.INVOKEINTERFACE, "org/dsi/ifc/carplay/DSICarplay", "setNotification", "([ILorg/dsi/ifc/base/DSIListener;)V")) {
                InsnList p = new InsnList();
                p.add(new VarInsnNode(Opcodes.ALOAD, 0));
                p.add(new FieldInsnNode(Opcodes.GETFIELD, HSM, "dsiCarplay", "Lorg/dsi/ifc/carplay/DSICarplay;"));
                MethodInsnNode call = new MethodInsnNode(Opcodes.INVOKESTATIC, NP, "attach", "(Lorg/dsi/ifc/carplay/DSICarplay;)V", false);
                p.add(call);
                m.instructions.insert(n, p);
                Guard.wrapCall(HSM, m, call, Guard.popArgsReturnZero(call.desc));
                n = call;
                hits++;
            }
        }
        expect(hits == 1, "HsmTarget.initializeDSI setNotification count " + hits);
        boolean field = false;
        for (FieldNode f : cn.fields) field |= f.name.equals("dsiCarplay") && f.desc.equals("Lorg/dsi/ifc/carplay/DSICarplay;");
        expect(field, "HsmTarget.dsiCarplay field");
        write(cn);
    }

    // ------------------------------------------------- 2. CurrentStationInfo
    static void patchCurrentStationInfo() throws IOException, AnalyzerException {
        ClassNode cn = read(in, CSI);
        toFactoryVersion(cn);

        // init(): NowPlaying.register(this) before its single areturn
        MethodNode init = method(cn, "init", "(Lde/vw/mib/bap/mqbab2/common/api/stages/BAPStageInitializer;)Lde/vw/mib/bap/datatypes/BAPEntity;");
        int returns = 0;
        for (AbstractInsnNode n : init.instructions.toArray()) if (n.getOpcode() == Opcodes.ARETURN) {
            InsnList p = new InsnList();
            p.add(new VarInsnNode(Opcodes.ALOAD, 0));
            MethodInsnNode call = new MethodInsnNode(Opcodes.INVOKESTATIC, NP, "register", "(L" + CSI + ";)V", false);
            p.add(call);
            init.instructions.insertBefore(n, p);
            Guard.wrapCall(CSI, init, call, Guard.popArgsReturnZero(call.desc));
            returns++;
        }
        expect(returns == 1, "CurrentStationInfo.init areturn count " + returns);

        // uninitialize(): NowPlaying.unregister(this) first
        MethodNode un = method(cn, "uninitialize", "()V");
        InsnList u = new InsnList();
        u.add(new VarInsnNode(Opcodes.ALOAD, 0));
        MethodInsnNode ucall = new MethodInsnNode(Opcodes.INVOKESTATIC, NP, "unregister", "(L" + CSI + ";)V", false);
        u.add(ucall);
        un.instructions.insert(u);
        Guard.wrapCall(CSI, un, ucall, Guard.popArgsReturnZero(ucall.desc));

        // setStationInfoForMirrorLink(status): at entry
        //     if (NowPlaying.fill(getSmartphoneIntegrationService().getSmarphoneIntegrationActiveConnectionType(), status)) return;
        // The two calls are copied from the method's own first instructions (asserted).
        MethodNode ml = method(cn, "setStationInfoForMirrorLink", "(L" + STATUS + ";)V");
        AbstractInsnNode i0 = real(ml.instructions.getFirst());
        AbstractInsnNode i1 = real(i0.getNext());
        AbstractInsnNode i2 = real(i1.getNext());
        AbstractInsnNode i3 = real(i2.getNext());
        expect(i0.getOpcode() == Opcodes.ALOAD && ((VarInsnNode) i0).var == 0, "mirrorlink aload_0");
        expect(isCall(i1, Opcodes.INVOKEVIRTUAL, CSI, "getSmartphoneIntegrationService",
                "()Lde/vw/mib/bap/mqbab2/common/api/smartphoneintegration/SmartphoneIntegrationService;"), "mirrorlink service getter");
        expect(isCall(i2, Opcodes.INVOKEINTERFACE, "de/vw/mib/bap/mqbab2/common/api/smartphoneintegration/SmartphoneIntegrationService",
                "getSmarphoneIntegrationActiveConnectionType", "()I"), "mirrorlink connection type");
        expect(i3 instanceof TableSwitchInsnNode && ((TableSwitchInsnNode) i3).min == 0 && ((TableSwitchInsnNode) i3).max == 4, "mirrorlink switch 0..4");
        InsnList p = new InsnList();
        LabelNode stock = new LabelNode();
        p.add(new VarInsnNode(Opcodes.ALOAD, 0));
        p.add(((MethodInsnNode) i1).clone(null));
        p.add(((MethodInsnNode) i2).clone(null));
        p.add(new VarInsnNode(Opcodes.ALOAD, 1));
        MethodInsnNode fcall = new MethodInsnNode(Opcodes.INVOKESTATIC, NP, "fill", "(IL" + STATUS + ";)Z", false);
        p.add(fcall);
        p.add(new JumpInsnNode(Opcodes.IFEQ, stock));
        p.add(new InsnNode(Opcodes.RETURN));
        p.add(stock);
        ml.instructions.insert(p);
        Guard.wrapCall(CSI, ml, fcall, Guard.popArgsReturnZero(fcall.desc));   // failure -> false -> stock text
        write(cn);
    }
}
