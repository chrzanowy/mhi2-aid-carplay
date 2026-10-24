/* SPDX-License-Identifier: GPL-3.0-or-later. Host build tool, never installed on the unit. */
import org.objectweb.asm.*;
import org.objectweb.asm.tree.*;
import org.objectweb.asm.tree.analysis.AnalyzerException;
import java.io.*;
import java.nio.file.*;

/**
 * Packages F (zoom) and G (day/night) as hooks into the firmware's own classes. Every hook asserts the
 * exact stock pattern and count; anything else aborts the build. Every call into our helpers is wrapped by
 * Guard.wrapCall (buildtools/Guard.java): if J9 cannot load or run the helper, the stock path continues.
 *
 * usage: java PatchExtras zoom|dn <stockClassesDir> <helperClassesDir> <outDir> <helperClass>...
 */
public class PatchExtras {
    static final int CLASS_VERSION = 46;
    static Path in, helper, out;

    public static void main(String[] a) throws Exception {
        in = Paths.get(a[1]); helper = Paths.get(a[2]); out = Paths.get(a[3]);
        if (a[0].equals("zoom")) patchKeyPanel();
        else if (a[0].equals("dn")) patchAslHandler();
        else throw new IllegalArgumentException(a[0]);
        for (int i = 4; i < a.length; i++) downgradeHelper(a[i]);
        System.out.println("OK " + a[0]);
    }

    static void expect(boolean ok, String what) {
        if (!ok) throw new IllegalStateException("pattern mismatch: " + what);
    }

    static ClassNode read(Path dir, String name) throws IOException {
        ClassNode cn = new ClassNode();
        new ClassReader(Files.readAllBytes(dir.resolve(name + ".class"))).accept(cn, ClassReader.SKIP_FRAMES);
        return cn;
    }

    static void toFactoryVersion(ClassNode cn) {
        expect(cn.version == 46 || cn.version == 49, cn.name + " version " + cn.version);
        for (MethodNode m : cn.methods)
            for (AbstractInsnNode n : m.instructions)
                if (n instanceof LdcInsnNode) expect(!(((LdcInsnNode) n).cst instanceof Type), cn.name + "." + m.name + " uses a class literal");
        cn.version = CLASS_VERSION;
    }

    static void write(ClassNode cn) throws IOException {
        if (!cn.name.startsWith("com/pmcp/")) Guard.checkAllGuarded(cn, "com/pmcp/");
        if (cn.version != CLASS_VERSION) throw new IllegalStateException(cn.name + " version " + cn.version);
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

    // F: DSIKeyPanelDispatcher.updateKey2(keyboard, key, state, p3, valid), at entry:
    //     if (keyboard == 4) ZoomHook.onKey2(same args)       (guarded; other keyboards never reach our code)
    static void patchKeyPanel() throws IOException, AnalyzerException {
        String name = "de/esolutions/fw/dsi/keypanel/DSIKeyPanelDispatcher";
        ClassNode cn = read(in, name);
        toFactoryVersion(cn);
        MethodNode m = method(cn, "updateKey2", "(IIIII)V");
        expect((m.access & Opcodes.ACC_STATIC) == 0, "updateKey2 is an instance method");
        InsnList p = new InsnList();
        LabelNode stock = new LabelNode();
        p.add(new VarInsnNode(Opcodes.ILOAD, 1));
        p.add(new InsnNode(Opcodes.ICONST_4));
        p.add(new JumpInsnNode(Opcodes.IF_ICMPNE, stock));
        for (int i = 1; i <= 5; i++) p.add(new VarInsnNode(Opcodes.ILOAD, i));
        MethodInsnNode call = new MethodInsnNode(Opcodes.INVOKESTATIC, "com/pmcp/zoom/ZoomHook", "onKey2", "(IIIII)V", false);
        p.add(call);
        p.add(stock);
        m.instructions.insert(p);
        Guard.wrapCall(name, m, call, Guard.popArgsReturnZero(call.desc));
        write(cn);
    }

    // G: ASLHandler, right after the single stock dsi.startService(config): DayNight.sessionStarted(target, properties);
    //    at the entry of handleDayNightMode(ev): DayNight.beforeHandle(ev, properties). Both guarded.
    static void patchAslHandler() throws IOException, AnalyzerException {
        String name = "de/vw/mib/asl/internal/carplay/target/ASLHandler";
        ClassNode cn = read(in, name);
        toFactoryVersion(cn);
        int hits = 0;
        MethodNode startMethod = null;
        MethodInsnNode startHook = null;
        for (MethodNode m : cn.methods)
            for (AbstractInsnNode n = m.instructions.getFirst(); n != null; n = n.getNext())
                if (isCall(n, Opcodes.INVOKEINTERFACE, "org/dsi/ifc/carplay/DSICarplay", "startService", "(Lorg/dsi/ifc/carplay/ServiceConfiguration;)V")) {
                    InsnList p = new InsnList();
                    p.add(new VarInsnNode(Opcodes.ALOAD, 0));
                    p.add(new FieldInsnNode(Opcodes.GETFIELD, name, "target", "Lde/vw/mib/asl/internal/carplay/target/HsmTarget;"));
                    p.add(new VarInsnNode(Opcodes.ALOAD, 0));
                    p.add(new FieldInsnNode(Opcodes.GETFIELD, name, "properties", "Lde/vw/mib/asl/internal/carplay/common/CarPlayGlobalProperies;"));
                    startHook = new MethodInsnNode(Opcodes.INVOKESTATIC, "com/pmcp/dn/DayNight", "sessionStarted",
                            "(Lde/vw/mib/asl/internal/carplay/target/HsmTarget;Lde/vw/mib/asl/internal/carplay/common/CarPlayGlobalProperies;)V", false);
                    p.add(startHook);
                    m.instructions.insert(n, p);
                    startMethod = m;
                    hits++;
                    expect((m.access & Opcodes.ACC_STATIC) == 0, "startService caller is an instance method");
                }
        expect(hits == 1, "ASLHandler startService count " + hits);
        boolean t = false, pr = false;
        for (FieldNode f : cn.fields) {
            t |= f.name.equals("target") && f.desc.equals("Lde/vw/mib/asl/internal/carplay/target/HsmTarget;");
            pr |= f.name.equals("properties") && f.desc.equals("Lde/vw/mib/asl/internal/carplay/common/CarPlayGlobalProperies;");
        }
        expect(t && pr, "ASLHandler fields target/properties");
        Guard.wrapCall(name, startMethod, startHook, Guard.popArgsReturnZero(startHook.desc));

        // handleDayNightMode: the stock body starts with ev.getBoolean(0) (asserted), so the hook runs before it
        MethodNode h = method(cn, "handleDayNightMode", "(Lde/vw/mib/genericevents/EventGeneric;)V");
        AbstractInsnNode h0 = h.instructions.getFirst();
        while (h0 != null && h0.getOpcode() < 0) h0 = h0.getNext();
        AbstractInsnNode h1 = h0.getNext(), h2 = h1.getNext();
        expect(h0.getOpcode() == Opcodes.ALOAD && ((VarInsnNode) h0).var == 1 && h1.getOpcode() == Opcodes.ICONST_0
                && isCall(h2, Opcodes.INVOKEVIRTUAL, "de/vw/mib/genericevents/EventGeneric", "getBoolean", "(I)Z"),
                "handleDayNightMode starts with ev.getBoolean(0)");
        InsnList q = new InsnList();
        q.add(new VarInsnNode(Opcodes.ALOAD, 1));
        q.add(new VarInsnNode(Opcodes.ALOAD, 0));
        q.add(new FieldInsnNode(Opcodes.GETFIELD, name, "properties", "Lde/vw/mib/asl/internal/carplay/common/CarPlayGlobalProperies;"));
        MethodInsnNode before = new MethodInsnNode(Opcodes.INVOKESTATIC, "com/pmcp/dn/DayNight", "beforeHandle",
                "(Lde/vw/mib/genericevents/EventGeneric;Lde/vw/mib/asl/internal/carplay/common/CarPlayGlobalProperies;)V", false);
        q.add(before);
        h.instructions.insert(q);
        Guard.wrapCall(name, h, before, Guard.popArgsReturnZero(before.desc));
        write(cn);
    }
}
