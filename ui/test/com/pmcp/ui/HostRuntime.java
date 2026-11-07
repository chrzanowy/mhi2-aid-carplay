/* SPDX-License-Identifier: GPL-3.0-or-later. Host test support, never installed on the unit. */
package com.pmcp.ui;

import java.lang.invoke.MethodHandles;
import java.lang.reflect.Field;
import java.lang.reflect.InvocationHandler;
import java.lang.reflect.Method;
import java.lang.reflect.Modifier;
import java.lang.reflect.Proxy;
import java.util.LinkedHashMap;
import java.util.Map;
import org.objectweb.asm.ClassWriter;
import org.objectweb.asm.MethodVisitor;
import org.objectweb.asm.Opcodes;
import org.objectweb.asm.Type;

/**
 * Lets the factory widget and view-handler classes of the converted MU1161 jar run in a desktop JVM:
 *  - every service the widgets ask for (logger, repaint, fonts, ...) is a do-nothing proxy;
 *  - a concrete subclass of the (patched) abstract AbstractViewHandler is generated with ASM, every abstract method
 *    returning a default value, and defined in the factory package (its package-private methods need that).
 */
final class HostRuntime {
    private HostRuntime() {
    }

    static final class Stub implements InvocationHandler {
        final Class<?> type;

        Stub(Class<?> type) {
            this.type = type;
        }

        static Object of(Class<?> type) {
            return Proxy.newProxyInstance(HostRuntime.class.getClassLoader(), new Class<?>[] {type}, new Stub(type));
        }

        public Object invoke(Object proxy, Method method, Object[] args) {
            String name = method.getName();
            if (name.equals("hashCode")) return System.identityHashCode(proxy);
            if (name.equals("equals")) return proxy == args[0];
            if (name.equals("toString")) return "Stub(" + type.getName() + ")";
            return defaultValue(method.getReturnType());
        }
    }

    static Object defaultValue(Class<?> r) {
        if (r == void.class) return null;
        if (r == boolean.class) return false;
        if (r == int.class) return 0;
        if (r == long.class) return 0L;
        if (r == short.class) return (short) 0;
        if (r == byte.class) return (byte) 0;
        if (r == float.class) return 0f;
        if (r == double.class) return 0d;
        if (r == char.class) return (char) 0;
        if (r.isInterface()) return Stub.of(r);
        return null;
    }

    static void installServices() throws Exception {
        String[] packages = {"widgets", "animation", "graphics", "graphics.font", "graphics.image", "graphics.display",
            "repaint", "timer", "event", "datapool", "input", "format", "configuration", "sound", "speller",
            "widgets.speller"};
        for (String p : packages) {
            Class<?> c = Class.forName("de.vw.mib." + p + ".internal.ServiceManager");
            for (Field f : c.getDeclaredFields()) {
                int m = f.getModifiers();
                if (f.getType().isInterface() && Modifier.isStatic(m) && !Modifier.isFinal(m)) {
                    f.setAccessible(true);
                    if (f.get(null) == null) {
                        f.set(null, Stub.of(f.getType()));
                    }
                }
            }
        }
    }

    static final String AVH = "de/vw/mib/view/internal/AbstractViewHandler";
    private static Class<?> handlerClass;

    /** de.vw.mib.view.internal.HostViewHandler extends the AbstractViewHandler on the class path. */
    static synchronized Class<?> handlerClass() throws Exception {
        if (handlerClass != null) {
            return handlerClass;
        }
        Class<?> base = Class.forName(AVH.replace('/', '.'));
        Map<String, Method> abstracts = new LinkedHashMap<String, Method>();
        collectAbstract(base, abstracts);
        ClassWriter cw = new ClassWriter(ClassWriter.COMPUTE_MAXS | ClassWriter.COMPUTE_FRAMES);
        String name = "de/vw/mib/view/internal/HostViewHandler";
        cw.visit(Opcodes.V1_8, Opcodes.ACC_PUBLIC, name, null, AVH, null);
        MethodVisitor init = cw.visitMethod(Opcodes.ACC_PUBLIC, "<init>", "()V", null, null);
        init.visitCode();
        init.visitVarInsn(Opcodes.ALOAD, 0);
        init.visitMethodInsn(Opcodes.INVOKESPECIAL, AVH, "<init>", "()V", false);
        init.visitInsn(Opcodes.RETURN);
        init.visitMaxs(0, 0);
        init.visitEnd();
        for (Method m : abstracts.values()) {
            int access = Modifier.isPublic(m.getModifiers()) ? Opcodes.ACC_PUBLIC
                    : Modifier.isProtected(m.getModifiers()) ? Opcodes.ACC_PROTECTED : 0;
            MethodVisitor mv = cw.visitMethod(access, m.getName(), Type.getMethodDescriptor(m), null, null);
            mv.visitCode();
            Type r = Type.getReturnType(m);
            switch (r.getSort()) {
                case Type.VOID: mv.visitInsn(Opcodes.RETURN); break;
                case Type.BOOLEAN: case Type.BYTE: case Type.CHAR: case Type.SHORT: case Type.INT:
                    mv.visitInsn(Opcodes.ICONST_0); mv.visitInsn(Opcodes.IRETURN); break;
                case Type.LONG: mv.visitInsn(Opcodes.LCONST_0); mv.visitInsn(Opcodes.LRETURN); break;
                case Type.FLOAT: mv.visitInsn(Opcodes.FCONST_0); mv.visitInsn(Opcodes.FRETURN); break;
                case Type.DOUBLE: mv.visitInsn(Opcodes.DCONST_0); mv.visitInsn(Opcodes.DRETURN); break;
                default: mv.visitInsn(Opcodes.ACONST_NULL); mv.visitInsn(Opcodes.ARETURN);
            }
            mv.visitMaxs(0, 0);
            mv.visitEnd();
        }
        cw.visitEnd();
        handlerClass = MethodHandles.privateLookupIn(base, MethodHandles.lookup()).defineClass(cw.toByteArray());
        return handlerClass;
    }

    private static void collectAbstract(Class<?> type, Map<String, Method> out) {
        Map<String, Boolean> concrete = new LinkedHashMap<String, Boolean>();
        for (Class<?> c = type; c != null; c = c.getSuperclass()) {
            for (Method m : c.getDeclaredMethods()) {
                String key = m.getName() + Type.getMethodDescriptor(m);
                if (!Modifier.isAbstract(m.getModifiers())) concrete.putIfAbsent(key, true);
            }
        }
        java.util.ArrayDeque<Class<?>> queue = new java.util.ArrayDeque<Class<?>>();
        for (Class<?> c = type; c != null; c = c.getSuperclass()) {
            for (Method m : c.getDeclaredMethods()) {
                if (Modifier.isAbstract(m.getModifiers())) {
                    String key = m.getName() + Type.getMethodDescriptor(m);
                    if (!concrete.containsKey(key)) out.putIfAbsent(key, m);
                }
            }
            for (Class<?> i : c.getInterfaces()) queue.add(i);
        }
        while (!queue.isEmpty()) {
            Class<?> i = queue.poll();
            for (Method m : i.getDeclaredMethods()) {
                if (Modifier.isStatic(m.getModifiers())) continue;
                String key = m.getName() + Type.getMethodDescriptor(m);
                if (!concrete.containsKey(key)) out.putIfAbsent(key, m);
            }
            for (Class<?> j : i.getInterfaces()) queue.add(j);
        }
    }

    /** A handler at lifecycle CREATED (1) whose root widget is the given view, as after create(). */
    static Object createdHandler(Object view) throws Exception {
        Class<?> c = handlerClass();
        Object handler = c.getDeclaredConstructor().newInstance();
        Class<?> base = c.getSuperclass();
        Field life = base.getDeclaredField("lifeCycle");
        life.setAccessible(true);
        life.setInt(handler, 1);
        Class<?> cdClass = Class.forName("de.vw.mib.view.internal.CloneData");
        Object cd = cdClass.getConstructor(int.class, int.class).newInstance(1, 0);
        Object[] widgets = (Object[]) cdClass.getField("widgets").get(cd);
        widgets[0] = view;
        Field cd0 = base.getDeclaredField("cd0");
        cd0.setAccessible(true);
        cd0.set(handler, cd);
        for (String name : new String[] {"logger", "services", "appServices"}) {
            Field f = base.getDeclaredField(name);
            f.setAccessible(true);
            if (!f.getType().isInterface()) throw new IllegalStateException(name + " is not an interface");
            f.set(handler, Stub.of(f.getType()));
        }
        return handler;
    }

    static void call(Object handler, String name) throws Exception {
        Method m = handler.getClass().getSuperclass().getDeclaredMethod(name);
        m.setAccessible(true);
        try {
            m.invoke(handler);
        } catch (java.lang.reflect.InvocationTargetException e) {
            if (e.getCause() instanceof Exception) throw (Exception) e.getCause();
            throw e;
        }
    }

    /** The factory init(boolean): View.init() runs over the tree, our clones included. */
    static void init(Object handler) throws Exception {
        Method m = handler.getClass().getSuperclass().getDeclaredMethod("init", boolean.class);
        m.setAccessible(true);
        try {
            m.invoke(handler, Boolean.FALSE);
        } catch (java.lang.reflect.InvocationTargetException e) {
            if (e.getCause() instanceof Exception) throw (Exception) e.getCause();
            throw e;
        }
    }

    static void fatal(Object handler, RuntimeException error) throws Exception {
        Method m = handler.getClass().getSuperclass().getDeclaredMethod("fatalError", RuntimeException.class);
        m.setAccessible(true);
        m.invoke(handler, error);
    }

    static void setLifeCycle(Object handler, int value) throws Exception {
        Field life = handler.getClass().getSuperclass().getDeclaredField("lifeCycle");
        life.setAccessible(true);
        life.setInt(handler, value);
    }
}
