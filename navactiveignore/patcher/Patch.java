/* SPDX-License-Identifier: GPL-3.0-or-later
 * Based on tomasz-twardzicki MHI2-Carplay-Maps MU1427/NavActiveIgnore/patcher/Patch.java.
 * Host build tool, never installed on the unit. */
import org.objectweb.asm.*;
import org.objectweb.asm.tree.*;
import org.objectweb.asm.tree.analysis.AnalyzerException;
import java.io.*;
import java.nio.file.*;
import java.util.*;

/**
 * Builds NavActiveIgnore classes by patching the firmware's own classes
 * (converted from /ifs/lsd.jxe). Every patch asserts the exact instruction
 * pattern it expects and aborts otherwise. Every call into the helper is wrapped by Guard.wrapCall
 * (buildtools/Guard.java): if J9 cannot load or run it, the stock path continues.
 *
 * Firmware-specific HMI property IDs are arguments, never guessed:
 *   K4525 (MU1367): CarPlay nav active 2910009, Android Auto nav active 2910005.
 *   MU1427 (Tomasz): 3010002 and 3110002.
 *
 * usage: java Patch <stockClassesDir> <helperClassesDir> <outDir> <carplayNavProp> <aaNavProp>
 */
public class Patch {
    static final int CLASS_VERSION = 46; // factory J9 needs 46; desktop Java accepts 49 and hides the error
    static final String HELPER = "de/vw/mib/navactiveignore/NavActiveIgnore";
    static Path in, helper, out;
    static int carplayNavProp, aaNavProp;

    public static void main(String[] a) throws Exception {
        if (a.length != 5) throw new IllegalArgumentException("usage: Patch <stock> <helper> <out> <carplayNavProp> <aaNavProp>");
        in = Paths.get(a[0]); helper = Paths.get(a[1]); out = Paths.get(a[2]);
        carplayNavProp = Integer.parseInt(a[3]); aaNavProp = Integer.parseInt(a[4]);
        patchDSICarplayProxy();
        patchCarPlayModeHandling();
        patchASLNavigationServices();
        patchNavigationListener();
        patchRequestHandler();
        // No ChangeDataRate change: both of Tomasz's attempts left the cluster on "loading map".
        downgradeHelper(HELPER);
        System.out.println("OK");
    }

    // ---------------------------------------------------------------- utils
    static ClassNode read(String name) throws IOException {
        ClassNode cn = new ClassNode();
        new ClassReader(Files.readAllBytes(in.resolve(name + ".class"))).accept(cn, ClassReader.SKIP_FRAMES);
        expect(cn.version == CLASS_VERSION, name + " stock version " + cn.version);
        return cn;
    }

    static void write(ClassNode cn) throws IOException {
        if (cn.version != CLASS_VERSION) throw new IllegalStateException(cn.name + " version " + cn.version);
        if (cn.name.equals("de/esolutions/fw/comm/dsi/carplay/impl/DSICarplayProxy")) Guard.checkAllGuarded(cn, HELPER);
        ClassWriter cw = new ClassWriter(ClassWriter.COMPUTE_MAXS); // <50: no frames needed
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
        if (r == null) throw new IllegalStateException("method not found: " + cn.name + "." + name + desc);
        return r;
    }

    static AbstractInsnNode real(AbstractInsnNode n) {
        while (n != null && n.getOpcode() < 0) n = n.getNext();
        return n;
    }

    static AbstractInsnNode realPrev(AbstractInsnNode n) {
        while (n != null && n.getOpcode() < 0) n = n.getPrevious();
        return n;
    }

    static boolean isMethod(AbstractInsnNode n, int op, String owner, String name) {
        return n instanceof MethodInsnNode && n.getOpcode() == op
                && ((MethodInsnNode) n).owner.equals(owner) && ((MethodInsnNode) n).name.equals(name);
    }

    static boolean isLdcInt(AbstractInsnNode n, int v) {
        return n instanceof LdcInsnNode && Integer.valueOf(v).equals(((LdcInsnNode) n).cst);
    }

    static boolean isIntConst(AbstractInsnNode n, int v) {
        if (n == null) return false;
        int op = n.getOpcode();
        if (op >= Opcodes.ICONST_M1 && op <= Opcodes.ICONST_5) return op - Opcodes.ICONST_0 == v;
        if (op == Opcodes.BIPUSH || op == Opcodes.SIPUSH) return ((IntInsnNode) n).operand == v;
        return isLdcInt(n, v);
    }

    /** previous k real instructions, oldest first */
    static AbstractInsnNode[] back(AbstractInsnNode n, int k) {
        AbstractInsnNode[] r = new AbstractInsnNode[k];
        AbstractInsnNode c = n;
        for (int i = k - 1; i >= 0; i--) { c = realPrev(c.getPrevious()); r[i] = c; }
        return r;
    }

    static boolean isPropertyCall(AbstractInsnNode n, int prop, boolean value) {
        if (!isMethod(n, Opcodes.INVOKEINTERFACE, "de/vw/mib/asl/ASLPropertyManager", "valueChangedBoolean")) return false;
        AbstractInsnNode[] b = back(n, 3);
        return b[0].getOpcode() == Opcodes.GETSTATIC && isLdcInt(b[1], prop)
                && b[2].getOpcode() == (value ? Opcodes.ICONST_1 : Opcodes.ICONST_0);
    }

    static void expect(boolean ok, String what) {
        if (!ok) throw new IllegalStateException("pattern mismatch: " + what);
    }

    static void removeAll(InsnList l, AbstractInsnNode... ns) { for (AbstractInsnNode n : ns) l.remove(n); }

    static void downgradeHelper(String name) throws IOException {
        ClassNode cn = new ClassNode();
        new ClassReader(Files.readAllBytes(helper.resolve(name + ".class"))).accept(cn, ClassReader.SKIP_FRAMES);
        cn.version = CLASS_VERSION;
        // Guard against post-1.2 library use slipping in.
        for (MethodNode m : cn.methods)
            for (AbstractInsnNode n : m.instructions) {
                if (n instanceof MethodInsnNode && ((MethodInsnNode) n).owner.startsWith("java/lang/StringBuilder"))
                    throw new IllegalStateException("StringBuilder in helper");
                if (n instanceof InvokeDynamicInsnNode) throw new IllegalStateException("indy in helper");
                if (n instanceof LdcInsnNode && ((LdcInsnNode) n).cst instanceof Type)
                    throw new IllegalStateException("class literal in helper");
            }
        cn.sourceFile = "NavActiveIgnore.java";
        write(cn);
    }

    // ------------------------------------------------- 1. DSICarplayProxy
    // Never send "native navigation takes ownership" to the iPhone: CarPlay
    // keeps its own route guidance while the stock map runs in the cluster.
    static void patchDSICarplayProxy() throws IOException, AnalyzerException {
        ClassNode cn = read("de/esolutions/fw/comm/dsi/carplay/impl/DSICarplayProxy");
        MethodNode m = method(cn, "requestModeChange",
                "([Lorg/dsi/ifc/carplay/ResourceRequest;[Lorg/dsi/ifc/carplay/AppStateRequest;Ljava/lang/String;)V");
        int tmp = m.maxLocals; // fresh local
        m.maxLocals = tmp + 1; // Guard allocates its own locals after it
        InsnList p = new InsnList();
        LabelNode go = new LabelNode();
        p.add(new VarInsnNode(Opcodes.ALOAD, 2));
        MethodInsnNode strip = new MethodInsnNode(Opcodes.INVOKESTATIC, HELPER, "stripNativeNavClaims",
                "([Lorg/dsi/ifc/carplay/AppStateRequest;)[Lorg/dsi/ifc/carplay/AppStateRequest;", false);
        p.add(strip);
        p.add(new VarInsnNode(Opcodes.ASTORE, tmp));
        p.add(new VarInsnNode(Opcodes.ALOAD, 1));
        p.add(new VarInsnNode(Opcodes.ALOAD, 2));
        p.add(new VarInsnNode(Opcodes.ALOAD, tmp));
        MethodInsnNode drop = new MethodInsnNode(Opcodes.INVOKESTATIC, HELPER, "dropRequest",
                "([Lorg/dsi/ifc/carplay/ResourceRequest;[Lorg/dsi/ifc/carplay/AppStateRequest;[Lorg/dsi/ifc/carplay/AppStateRequest;)Z", false);
        p.add(drop);
        p.add(new JumpInsnNode(Opcodes.IFEQ, go));
        p.add(new InsnNode(Opcodes.RETURN));
        p.add(go);
        p.add(new VarInsnNode(Opcodes.ALOAD, tmp));
        p.add(new VarInsnNode(Opcodes.ASTORE, 2));
        // sanity: original body serialises param 2 via the anonymous ISerializable
        AbstractInsnNode first = real(m.instructions.getFirst());
        expect(first.getOpcode() == Opcodes.NEW && ((TypeInsnNode) first).desc.startsWith(cn.name + "$"),
                "DSICarplayProxy.requestModeChange prologue");
        m.instructions.insert(p);
        // helper failure: keep the stock request (strip -> the array unchanged, drop -> false)
        Guard.wrapCall(cn.name, m, strip, new InsnList());
        Guard.wrapCall(cn.name, m, drop, Guard.popArgsReturnZero(drop.desc));
        write(cn);
    }

    // --------------------------------------------- 2. CarPlayModeHandling
    // CarPlay nav active: do not raise the HMI property, do not mark CarPlay as
    // the active navigation and do not stop native guidance. HMI nav active: do
    // not reclaim navigation from the phone ("User initiated").
    // The K4525 exbox calls (setSmartphoneGuidanceActive/Inactive) stay stock:
    // they only reach DSIExBoxM, the external nav box.
    static void patchCarPlayModeHandling() throws IOException {
        ClassNode cn = read("de/vw/mib/asl/internal/carplay/common/CarPlayModeHandling");
        MethodNode m = method(cn, "handleModeChanges",
                "([Lorg/dsi/ifc/carplay/Resource;[Lorg/dsi/ifc/carplay/AppState;)V");
        InsnList l = m.instructions;
        int propTrue = 0, setNav2 = 0, stopG = 0, userInit = 0;
        for (AbstractInsnNode n = l.getFirst(); n != null; ) {
            AbstractInsnNode next = n.getNext();
            // (a) aslPropertyManager.valueChangedBoolean(carplayNavProp, true)
            if (isPropertyCall(n, carplayNavProp, true)) {
                AbstractInsnNode[] b = back(n, 3);
                removeAll(l, b[0], b[1], b[2], n); propTrue++;
            }
            // (b) properties.setActiveNavigation(2 /*CARPLAY*/)
            else if (isMethod(n, Opcodes.INVOKEVIRTUAL, "de/vw/mib/asl/internal/carplay/common/CarPlayGlobalProperies", "setActiveNavigation")) {
                AbstractInsnNode[] b = back(n, 3);
                if (b[0].getOpcode() == Opcodes.ALOAD && b[1].getOpcode() == Opcodes.GETFIELD && b[2].getOpcode() == Opcodes.ICONST_2) {
                    removeAll(l, b[0], b[1], b[2], n); setNav2++;
                }
            }
            // (c) navServices.stopGuidance(6) ; pop   ->  pop (drops navServices ref)
            else if (isMethod(n, Opcodes.INVOKEINTERFACE, "de/vw/mib/asl/api/navigation/ASLNavigationServices", "stopGuidance")) {
                AbstractInsnNode c6 = realPrev(n.getPrevious());
                AbstractInsnNode pop = real(n.getNext());
                expect(isIntConst(c6, 6) && pop.getOpcode() == Opcodes.POP, "stopGuidance(6);pop");
                next = pop.getNext();
                removeAll(l, c6, n);  // keep the POP: it now discards navServices
                stopG++;
            }
            // (d) getDSICarPlay().requestModeChange(res, states, "User initiated") -> discard args
            else if (isMethod(n, Opcodes.INVOKEINTERFACE, "org/dsi/ifc/carplay/DSICarplay", "requestModeChange")) {
                AbstractInsnNode s = realPrev(n.getPrevious());
                if (s instanceof LdcInsnNode && "User initiated".equals(((LdcInsnNode) s).cst)) {
                    InsnList r = new InsnList();
                    r.add(new InsnNode(Opcodes.POP2)); // string, states
                    r.add(new InsnNode(Opcodes.POP2)); // res, DSICarplay
                    l.insertBefore(n, r);
                    l.remove(n);
                    userInit++;
                }
            }
            n = next;
        }
        expect(propTrue == 1 && setNav2 == 1 && stopG == 1 && userInit == 1,
                "CarPlayModeHandling counts " + propTrue + "/" + setNav2 + "/" + stopG + "/" + userInit);
        write(cn);
    }

    // -------------------------------------------- 3. ASLNavigationServices
    // stopGuidance(6) is "stop because a smartphone took navigation": ignore it.
    static void patchASLNavigationServices() throws IOException {
        ClassNode cn = read("de/vw/mib/asl/internal/navigation/api/impl/ASLNavigationServices");
        MethodNode m = method(cn, "stopGuidance", "(I)I");
        InsnList p = new InsnList();
        LabelNode go = new LabelNode();
        p.add(new VarInsnNode(Opcodes.ILOAD, 1));
        p.add(new IntInsnNode(Opcodes.BIPUSH, 6));
        p.add(new JumpInsnNode(Opcodes.IF_ICMPNE, go));
        p.add(new InsnNode(Opcodes.ICONST_1));
        p.add(new InsnNode(Opcodes.IRETURN));
        p.add(go);
        m.instructions.insert(p);
        write(cn);
    }

    // ---------------------------------------- 4. AA NavigationListener
    static void patchNavigationListener() throws IOException {
        ClassNode cn = read("de/vw/mib/asl/internal/androidauto/target/NavigationListener");
        replaceBody(method(cn, "updateGuidanceActive", "(Z)V"), Opcodes.RETURN);
        replaceBody(method(cn, "stopGuidance", "()V"), Opcodes.RETURN);
        replaceBody(method(cn, "isGuidanceActive", "()Z"), Opcodes.IRETURN);
        write(cn);
    }

    static void replaceBody(MethodNode m, int ret) {
        m.instructions.clear();
        m.tryCatchBlocks.clear();
        if (m.localVariables != null) m.localVariables.clear();
        if (ret == Opcodes.IRETURN) m.instructions.add(new InsnNode(Opcodes.ICONST_0));
        m.instructions.add(new InsnNode(ret));
    }

    // -------------------------------------------- 5. AA RequestHandler
    // Both nav-focus requests are answered "projected" (2); native guidance is
    // never stopped and the AA-nav-active HMI property is not raised.
    static void patchRequestHandler() throws IOException {
        ClassNode cn = read("de/vw/mib/asl/internal/androidauto/target/RequestHandler");
        MethodNode m = method(cn, "performNavFocusRequestNotification", "(I)V");
        InsnList l = m.instructions;
        AbstractInsnNode sw = null;
        for (AbstractInsnNode n : l)
            if (n instanceof LookupSwitchInsnNode || n instanceof TableSwitchInsnNode) { expect(sw == null, "one switch"); sw = n; }
        expect(sw != null, "switch present");
        if (sw instanceof LookupSwitchInsnNode) {
            LookupSwitchInsnNode ls = (LookupSwitchInsnNode) sw;
            expect(ls.keys.equals(Arrays.asList(1, 2)), "lookupswitch keys {1,2}");
            ls.labels.set(0, ls.labels.get(1));   // case 1 -> case 2 body
        } else {
            TableSwitchInsnNode ts = (TableSwitchInsnNode) sw;
            expect(ts.min == 1 && ts.max == 2 && ts.labels.size() == 2, "tableswitch 1..2");
            ts.labels.set(0, ts.labels.get(1));   // case 1 -> case 2 body
        }
        int stop = 0, prop = 0;
        for (AbstractInsnNode n = l.getFirst(); n != null; ) {
            AbstractInsnNode next = n.getNext();
            if (isMethod(n, Opcodes.INVOKEVIRTUAL, "de/vw/mib/asl/internal/androidauto/target/NavigationListener", "stopGuidance")) {
                AbstractInsnNode[] b = back(n, 2);
                expect(b[0].getOpcode() == Opcodes.ALOAD && b[1].getOpcode() == Opcodes.GETFIELD, "navigationHandler.stopGuidance()");
                removeAll(l, b[0], b[1], n); stop++;
            } else if (isPropertyCall(n, aaNavProp, true)) {
                AbstractInsnNode[] b = back(n, 3);
                removeAll(l, b[0], b[1], b[2], n); prop++;
            }
            n = next;
        }
        expect(stop == 1 && prop == 1, "RequestHandler counts " + stop + "/" + prop);
        write(cn);
    }
}
