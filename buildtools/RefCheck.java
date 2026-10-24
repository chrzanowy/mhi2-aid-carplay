/* SPDX-License-Identifier: GPL-3.0-or-later. Host build tool, never installed on the unit.
 * From code review 2: J9 CDC 1.1 API check. javac --release 8 compiles against the JDK 8 library, so
 * a call that J9 does not have (StringBuilder, String.isEmpty, Integer.valueOf(int), java.util.Objects, ...) would pass
 * every build step and only fail in the car. The converted stock jar holds the unit's own java.* classes (from the JXE),
 * so every reference in our jars is resolved against it. Exit 1 on any problem.
 *
 * usage: java RefCheck <converted stock jar> <our jar>...
 */
import org.objectweb.asm.*;
import org.objectweb.asm.tree.*;
import java.io.*;
import java.util.*;
import java.util.zip.*;

/** For every class in the given mod jars: resolve every class/method/field reference against stock jar + mod jars. */
public class RefCheck {
    static Map<String, ClassNode> pool = new HashMap<>();
    static Map<String, String> origin = new HashMap<>();
    static void load(String jar, boolean override) throws IOException {
        try (ZipFile z = new ZipFile(jar)) {
            for (Enumeration<? extends ZipEntry> e = z.entries(); e.hasMoreElements();) {
                ZipEntry en = e.nextElement();
                if (!en.getName().endsWith(".class")) continue;
                ClassNode cn = new ClassNode();
                new ClassReader(z.getInputStream(en).readAllBytes()).accept(cn, ClassReader.SKIP_CODE | ClassReader.SKIP_DEBUG);
                if (override || !pool.containsKey(cn.name)) { pool.put(cn.name, cn); origin.put(cn.name, jar); }
            }
        }
    }
    static boolean hasMethod(String owner, String name, String desc, Set<String> seen) {
        if (owner.startsWith("[")) return true; // array clone etc
        if (!seen.add(owner)) return false;
        ClassNode c = pool.get(owner);
        if (c == null) return false;
        for (MethodNode m : c.methods) if (m.name.equals(name) && m.desc.equals(desc)) return true;
        if (c.superName != null && hasMethod(c.superName, name, desc, seen)) return true;
        for (String i : c.interfaces) if (hasMethod(i, name, desc, seen)) return true;
        return false;
    }
    static boolean hasField(String owner, String name, String desc, Set<String> seen) {
        if (!seen.add(owner)) return false;
        ClassNode c = pool.get(owner);
        if (c == null) return false;
        for (FieldNode f : c.fields) if (f.name.equals(name) && f.desc.equals(desc)) return true;
        if (c.superName != null && hasField(c.superName, name, desc, seen)) return true;
        for (String i : c.interfaces) if (hasField(i, name, desc, seen)) return true;
        return false;
    }
    static String elem(String t) { Type ty = Type.getType(t); while (ty.getSort()==Type.ARRAY) ty = ty.getElementType(); return ty.getSort()==Type.OBJECT ? ty.getInternalName() : null; }
    public static void main(String[] a) throws Exception {
        String stock = a[0];
        load(stock, false);
        for (int i = 1; i < a.length; i++) load(a[i], true);
        int bad = 0;
        for (int i = 1; i < a.length; i++) {
            try (ZipFile z = new ZipFile(a[i])) {
                for (Enumeration<? extends ZipEntry> e = z.entries(); e.hasMoreElements();) {
                    ZipEntry en = e.nextElement();
                    if (!en.getName().endsWith(".class")) continue;
                    ClassNode cn = new ClassNode();
                    byte[] b = z.getInputStream(en).readAllBytes();
                    new ClassReader(b).accept(cn, 0);
                    Set<String> msgs = new TreeSet<>();
                    if (cn.version != 46) msgs.add("version " + cn.version);
                    if (pool.get(cn.superName) == null) msgs.add("missing super " + cn.superName);
                    for (String itf : cn.interfaces) if (pool.get(itf) == null) msgs.add("missing itf " + itf);
                    if (cn.nestHostClass != null || cn.nestMembers != null) msgs.add("NestHost/NestMembers attr");
                    for (MethodNode m : cn.methods) {
                        for (AbstractInsnNode n : m.instructions) {
                            if (n instanceof MethodInsnNode) {
                                MethodInsnNode mi = (MethodInsnNode) n;
                                if (!pool.containsKey(mi.owner) && !mi.owner.startsWith("[")) msgs.add("missing class " + mi.owner + " (call " + mi.name + ")");
                                else if (!hasMethod(mi.owner, mi.name, mi.desc, new HashSet<>())) msgs.add("missing method " + mi.owner + "." + mi.name + mi.desc + " in " + m.name);
                            } else if (n instanceof FieldInsnNode) {
                                FieldInsnNode fi = (FieldInsnNode) n;
                                if (!pool.containsKey(fi.owner)) msgs.add("missing class " + fi.owner);
                                else if (!hasField(fi.owner, fi.name, fi.desc, new HashSet<>())) msgs.add("missing field " + fi.owner + "." + fi.name + " " + fi.desc);
                            } else if (n instanceof TypeInsnNode) {
                                String d = ((TypeInsnNode) n).desc;
                                String t = d.startsWith("[") ? elem(d) : d;
                                if (t != null && !pool.containsKey(t)) msgs.add("missing type " + t);
                            } else if (n instanceof LdcInsnNode) {
                                Object c = ((LdcInsnNode) n).cst;
                                if (c instanceof Type || c instanceof Handle || c instanceof ConstantDynamic) msgs.add("ldc " + c.getClass().getSimpleName() + " " + c);
                            } else if (n instanceof InvokeDynamicInsnNode) msgs.add("indy");
                            else if (n instanceof MultiANewArrayInsnNode) { String t = elem(((MultiANewArrayInsnNode) n).desc); if (t!=null && !pool.containsKey(t)) msgs.add("missing type " + t); }
                        }
                        for (TryCatchBlockNode t : m.tryCatchBlocks) if (t.type != null && !pool.containsKey(t.type)) msgs.add("missing catch type " + t.type);
                    }
                    for (String s : msgs) { System.out.println(a[i].replaceAll(".*/", "") + " " + cn.name + ": " + s); bad++; }
                }
            }
        }
        System.out.println("RefCheck problems: " + bad);
        System.exit(bad == 0 ? 0 : 1);
    }
}
