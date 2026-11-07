/* SPDX-License-Identifier: GPL-3.0-or-later. Host build tool, never installed on the unit. */
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.stream.Stream;
import org.objectweb.asm.ClassReader;
import org.objectweb.asm.ClassWriter;
import org.objectweb.asm.Opcodes;
import org.objectweb.asm.Type;
import org.objectweb.asm.tree.AbstractInsnNode;
import org.objectweb.asm.tree.ClassNode;
import org.objectweb.asm.tree.InsnList;
import org.objectweb.asm.tree.InvokeDynamicInsnNode;
import org.objectweb.asm.tree.LdcInsnNode;
import org.objectweb.asm.tree.MethodInsnNode;
import org.objectweb.asm.tree.MethodNode;
import org.objectweb.asm.tree.VarInsnNode;

/**
 * Package ui: five calls into com.pmcp.ui.MenuHook in a copy of the factory de.vw.mib.view.internal.AbstractViewHandler
 * of MU1161 (the same class file as MU1367 K4525, sha256 7afadc2e). The idea and the hook points are omonob's
 * BuildNativeHook (MHI2-Carplay-Maps src/vc-menu, GPL-3.0); here every call is guarded (buildtools/Guard.java).
 *
 *   init(Z)V       first                   MenuHook.attach(this)   (before the factory View.init)
 *   activate()V    before its one RETURN   MenuHook.refresh(this)
 *   deinit()V      before its one RETURN   MenuHook.detach(this)
 *   destroy()V     before its one RETURN   MenuHook.detach(this)
 *   fatalError(RuntimeException)V  first   MenuHook.failure(this, e)
 *
 * Nothing else in the class changes; TestMenuHookPatch compares every method with the factory one.
 *
 * Usage: PatchMenuHook <stockClassesDir> <helperClassesDir> <outDir>
 */
public final class PatchMenuHook {
    static final String HELPER = "com/pmcp/ui/MenuHook";
    static final String HELPER_PACKAGE = "com/pmcp/ui/";
    static final String TARGET = "de/vw/mib/view/internal/AbstractViewHandler";
    static final String TARGET_SHA256 = "7afadc2e226ef2b3444ea0e138e82fda5d839401d58e2beb0bcc00170972ddd6";
    static final int FACTORY_VERSION = 46;
    static final String[][] RETURN_HOOKS = {
        {"activate", "refresh"}, {"deinit", "detach"}, {"destroy", "detach"},
    };
    // At the start of init(boolean), not the end of setup(): the factory may run deinit -> init without a new setup
    // (ScreenAreaDude zoom paths), and the page must come back there too. Both are before View.init.
    static final String[][] START_HOOKS = {
        {"init", "(Z)V", "attach"},
    };

    public static void main(String[] args) throws Exception {
        expect(args.length == 3, "usage: PatchMenuHook <stock> <helpers> <output>");
        Path stock = Paths.get(args[0]);
        Path helpers = Paths.get(args[1]);
        Path output = Paths.get(args[2]);
        expect(!stock.toAbsolutePath().normalize().equals(output.toAbsolutePath().normalize()), "output equals stock");
        write(output, patch(Files.readAllBytes(stock.resolve(TARGET + ".class"))));
        copyHelpers(helpers, output);
        System.out.println("Menu hooks built");
    }

    static void expect(boolean condition, String message) {
        if (!condition) {
            throw new IllegalStateException("menu hook patch mismatch: " + message);
        }
    }

    static ClassNode patch(byte[] bytes) throws Exception {
        expect(sha256(bytes).equals(TARGET_SHA256), "stock hash " + TARGET);
        ClassNode node = read(bytes);
        expect(node.name.equals(TARGET), "class name " + node.name);
        expect(node.version == 46 || node.version == 49, "class version " + node.version);
        rejectModernInstructions(node);
        node.version = FACTORY_VERSION;
        String desc = "(L" + TARGET + ";)V";
        for (String[] hook : RETURN_HOOKS) {
            MethodNode method = method(node, hook[0], "()V");
            expect((method.access & Opcodes.ACC_STATIC) == 0, hook[0] + " instance method");
            int returns = 0;
            for (AbstractInsnNode insn : method.instructions.toArray()) {
                if (insn.getOpcode() == Opcodes.RETURN) {
                    InsnList call = new InsnList();
                    call.add(new VarInsnNode(Opcodes.ALOAD, 0));
                    MethodInsnNode invoke = new MethodInsnNode(Opcodes.INVOKESTATIC, HELPER, hook[1], desc, false);
                    call.add(invoke);
                    method.instructions.insertBefore(insn, call);
                    Guard.wrapCall(node.name, method, invoke, Guard.popArgsReturnZero(invoke.desc));
                    returns++;
                }
            }
            expect(returns == 1, hook[0] + " RETURN count " + returns);
        }
        for (String[] hook : START_HOOKS) {
            MethodNode method = method(node, hook[0], hook[1]);
            expect((method.access & Opcodes.ACC_STATIC) == 0, hook[0] + " instance method");
            InsnList call = new InsnList();
            call.add(new VarInsnNode(Opcodes.ALOAD, 0));
            MethodInsnNode invoke = new MethodInsnNode(Opcodes.INVOKESTATIC, HELPER, hook[2], desc, false);
            call.add(invoke);
            method.instructions.insert(call);
            Guard.wrapCall(node.name, method, invoke, Guard.popArgsReturnZero(invoke.desc));
        }
        MethodNode fatal = method(node, "fatalError", "(Ljava/lang/RuntimeException;)V");
        expect((fatal.access & Opcodes.ACC_STATIC) == 0, "fatalError instance method");
        InsnList call = new InsnList();
        call.add(new VarInsnNode(Opcodes.ALOAD, 0));
        call.add(new VarInsnNode(Opcodes.ALOAD, 1));
        MethodInsnNode failure = new MethodInsnNode(Opcodes.INVOKESTATIC, HELPER, "failure",
                "(L" + TARGET + ";Ljava/lang/RuntimeException;)V", false);
        call.add(failure);
        fatal.instructions.insert(call);
        Guard.wrapCall(node.name, fatal, failure, Guard.popArgsReturnZero(failure.desc));

        int calls = 0;
        for (MethodNode method : node.methods) {
            for (AbstractInsnNode insn : method.instructions) {
                if (insn instanceof MethodInsnNode && ((MethodInsnNode) insn).owner.startsWith(HELPER_PACKAGE)) {
                    calls++;
                }
            }
        }
        expect(calls == 5, "helper call count " + calls);
        Guard.checkAllGuarded(node, HELPER_PACKAGE);
        return node;
    }

    static ClassNode read(byte[] bytes) {
        ClassNode node = new ClassNode();
        new ClassReader(bytes).accept(node, ClassReader.SKIP_FRAMES);
        return node;
    }

    static String sha256(byte[] bytes) throws Exception {
        byte[] digest = MessageDigest.getInstance("SHA-256").digest(bytes);
        StringBuilder text = new StringBuilder();
        for (byte value : digest) {
            text.append(String.format("%02x", value & 255));
        }
        return text.toString();
    }

    static MethodNode method(ClassNode node, String name, String descriptor) {
        MethodNode found = null;
        for (MethodNode candidate : node.methods) {
            if (candidate.name.equals(name) && candidate.desc.equals(descriptor)) {
                expect(found == null, "duplicate " + node.name + "." + name);
                found = candidate;
            }
        }
        expect(found != null, "missing " + node.name + "." + name + descriptor);
        return found;
    }

    static void copyHelpers(Path helpers, Path output) throws IOException {
        Path root = helpers.resolve("com/pmcp/ui");
        List<Path> files = new ArrayList<Path>();
        try (Stream<Path> paths = Files.walk(root)) {
            paths.filter(path -> path.toString().endsWith(".class"))
                    .sorted(Comparator.comparing(Path::toString)).forEach(files::add);
        }
        expect(!files.isEmpty(), "no helper classes");
        boolean mainFound = false;
        for (Path path : files) {
            ClassNode node = read(Files.readAllBytes(path));
            expect(node.name.startsWith(HELPER_PACKAGE) && node.name.indexOf('/', HELPER_PACKAGE.length()) < 0,
                    "unexpected helper " + node.name);
            mainFound |= node.name.equals(HELPER);
            expect(node.version == 52, "helper must be compiled with --release 8");
            rejectModernInstructions(node);
            for (MethodNode method : node.methods) {
                method.localVariables = null;
            }
            node.version = FACTORY_VERSION;
            write(output, node);
        }
        expect(mainFound, "MenuHook missing");
    }

    static void rejectModernInstructions(ClassNode node) {
        for (MethodNode method : node.methods) {
            for (AbstractInsnNode instruction : method.instructions) {
                expect(!(instruction instanceof InvokeDynamicInsnNode), node.name + "." + method.name + " invokedynamic");
                if (instruction instanceof LdcInsnNode) {
                    Object constant = ((LdcInsnNode) instruction).cst;
                    expect(!(constant instanceof Type), node.name + "." + method.name + " class literal");
                }
                if (instruction instanceof MethodInsnNode) {
                    String owner = ((MethodInsnNode) instruction).owner;
                    expect(!owner.equals("java/lang/StringBuilder"), node.name + "." + method.name + " StringBuilder");
                    expect(!owner.startsWith("java/util/concurrent/") && !owner.startsWith("java/nio/"),
                            node.name + "." + method.name + " post-CDC API " + owner);
                }
            }
        }
    }

    static void write(Path output, ClassNode node) throws IOException {
        expect(node.version == FACTORY_VERSION, "output class version");
        ClassWriter writer = new ClassWriter(ClassWriter.COMPUTE_MAXS);
        node.accept(writer);
        Path path = output.resolve(node.name + ".class");
        Files.createDirectories(path.getParent());
        Files.write(path, writer.toByteArray());
        System.out.println("wrote " + node.name);
    }
}
