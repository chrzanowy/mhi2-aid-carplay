/* SPDX-License-Identifier: GPL-3.0-or-later. Host test, never installed on the unit. */
package com.pmcp.ui;

import de.vw.mib.widgets.Button;
import de.vw.mib.widgets.CommonImage;
import de.vw.mib.widgets.Container;
import de.vw.mib.widgets.DropDown;
import de.vw.mib.widgets.DropDownButton;
import de.vw.mib.widgets.InactiveArea;
import de.vw.mib.widgets.ListItem;
import de.vw.mib.widgets.TextArea;
import de.vw.mib.widgets.View;
import de.vw.mib.widgets.WidgetList;
import de.vw.mib.widgets.interfaces.WidgetCloneFactory;
import de.vw.mib.widgets.interfaces.WidgetCloneable;
import de.vw.mib.widgets.models.ContainerModel;
import de.vw.mib.widgets.models.TemplateListModel;
import de.vw.mib.widgets.models.WidgetModel;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Arrays;

/**
 * Host tests of package ui with the factory MU1161 classes (converted lsd.jar) and the patched AbstractViewHandler:
 * the speed-limit file rules (same bytes and conditions as pmcp.sh), and the page on a widget tree built from real
 * factory widget classes shaped like SMI_SETUP_MAIN, driven through the patched lifecycle methods.
 */
public final class TestUi {
    static int checks;
    static Path tmp;

    public static void main(String[] args) throws Exception {
        tmp = Files.createTempDirectory("pmcp-ui-test");
        UiLog.path = tmp.resolve("ui.log").toString();
        HostRuntime.installServices();
        speedLimitFile();
        speedLimitRules();
        pageLifecycle();
        missingDonorKeepsFactory();
        otherViewsUntouched();
        offSwitchAndFailure();
        trialSave();
        System.out.println("UI_HOST_PASS " + checks);
    }

    static void check(boolean ok, String what) {
        checks++;
        if (!ok) {
            throw new IllegalStateException("FAIL " + what);
        }
    }

    // ---------------------------------------------------------------- speed limit file

    static Path unit(String name) throws Exception {
        Path root = tmp.resolve(name);
        Files.createDirectories(root.resolve("mnt/persist/pmcp"));
        Files.createDirectories(root.resolve("mnt/app/carplaymaps"));
        Files.createDirectories(root.resolve("ramdisk"));
        return root;
    }

    static void javaSet(Path root, String set, String use, boolean confirmed) throws Exception {
        Files.write(root.resolve("mnt/app/carplaymaps/HMI_BOOT"),
                (set + " pmcp-guidance3.jar pmcp-sl2.jar\n").getBytes(StandardCharsets.US_ASCII));
        Files.write(root.resolve("mnt/persist/pmcp/last-boot"),
                ("set=" + set + " use=" + use + "\n").getBytes(StandardCharsets.US_ASCII));
        Path ok = root.resolve("mnt/persist/pmcp/ok." + set);
        if (confirmed) Files.write(ok, new byte[0]); else Files.deleteIfExists(ok);
    }

    static Path mode(Path root) {
        return root.resolve("mnt/persist/pmcp/native-speedlimit-mode");
    }

    static String bytes(Path p) throws Exception {
        return Files.exists(p) ? new String(Files.readAllBytes(p), StandardCharsets.ISO_8859_1) : null;
    }

    static String error(SpeedLimitSetting s, int choice) {
        try {
            s.select(choice);
            return null;
        } catch (Exception e) {
            return e.getMessage();
        }
    }

    static void speedLimitFile() throws Exception {
        Path root = unit("file");
        SpeedLimitSetting s = new SpeedLimitSetting(root.toString());
        check(s.count() == 3 && s.choice(0).equals("Off"), "three choices");
        check(s.current() == 0, "no file = off");
        check(error(s, 0) == null && !Files.exists(mode(root)), "off without a file creates nothing (as pmcp.sh)");
        String set = "nai-dbd031ec+rg-7b187484+sl-37b5d948";
        javaSet(root, set, "yes", true);
        check(error(s, 1) == null, "turnto saved");
        check("turnto\n".equals(bytes(mode(root))), "turnto bytes = pmcp.sh echo");
        check(s.current() == 1, "turnto read back");
        check(error(s, 2) == null && "street\n".equals(bytes(mode(root))) && s.current() == 2, "street bytes");
        check(error(s, 0) == null && "off\n".equals(bytes(mode(root))) && s.current() == 0, "off bytes over a file");
        check(!Files.exists(root.resolve("mnt/persist/pmcp/native-speedlimit-mode.pmcp-new")), "no staged file left");
        check(!Files.exists(root.resolve("ramdisk/pmcp-speedlimit.lock")), "lock released");
        String[][] invalid = {{"turnto", "-1"}, {"off\n\n", "-1"}, {"foo\n", "-1"}, {"TURNTO\n", "-1"}, {"", "-1"},
            {"street\n", "2"}};
        for (String[] c : invalid) {
            Files.write(mode(root), c[0].getBytes(StandardCharsets.ISO_8859_1));
            check(s.current() == Integer.parseInt(c[1]), "current() of '" + c[0].replace("\n", "\\n") + "'");
        }
        Files.write(mode(root), "turnto\n".getBytes(StandardCharsets.ISO_8859_1));
        // GEM holds the lock: nothing written, and the lock (not ours) stays
        Files.createDirectories(root.resolve("ramdisk/pmcp-speedlimit.lock"));
        String busy = error(s, 2);
        check(busy != null && busy.startsWith("Busy"), "busy lock refused: " + busy);
        check(error(s, 0) != null, "off also waits for the lock");
        check("turnto\n".equals(bytes(mode(root))), "file unchanged while locked");
        check(Files.isDirectory(root.resolve("ramdisk/pmcp-speedlimit.lock")), "foreign lock left in place");
        Files.delete(root.resolve("ramdisk/pmcp-speedlimit.lock"));
        // no /ramdisk: the lock cannot be taken, as pmcp.sh SPEEDLIMIT_LOCK_BUSY_OR_RAMDISK_UNAVAILABLE
        Files.delete(root.resolve("ramdisk"));
        check(error(s, 2) != null && "turnto\n".equals(bytes(mode(root))), "no ramdisk: nothing written");
        Files.createDirectories(root.resolve("ramdisk"));
        // mode path is a directory
        Files.delete(mode(root));
        Files.createDirectories(mode(root));
        check(error(s, 2) != null && Files.isDirectory(mode(root)), "directory at the mode path refused");
        check(s.current() == -1, "directory reads as invalid");
        Files.delete(mode(root));
    }

    static void speedLimitRules() throws Exception {
        Path root = unit("rules");
        SpeedLimitSetting s = new SpeedLimitSetting(root.toString());
        check(s.blocked(0) == null, "off always allowed");
        check(s.blocked(1) != null && s.blocked(2) != null, "no Java set: blocked");
        javaSet(root, "rg-7b187484", "yes", true);
        check(s.blocked(2).indexOf("sl") >= 0, "without sl: " + s.blocked(2));
        javaSet(root, "sl-37b5d948", "yes", true);
        check(s.blocked(2) == null, "street with sl only");
        check(s.blocked(1).indexOf("rg") >= 0, "turnto needs rg: " + s.blocked(1));
        check(error(s, 1) != null && !Files.exists(mode(root)), "turnto without rg not written");
        javaSet(root, "rg-aa-4f9215bf+sl-37b5d948", "yes", true);
        check(s.blocked(1) != null, "rg-aa is not rg (pmcp.sh current_set)");
        javaSet(root, "rg-7b187484+sl-37b5d948+ui-12345678", "trial", true);
        check(s.blocked(1) == null && s.blocked(2) == null, "confirmed set in its trial boot");
        javaSet(root, "rg-7b187484+sl-37b5d948", "yes", false);
        check(s.blocked(2).indexOf("Save") >= 0, "unconfirmed set: " + s.blocked(2));
        javaSet(root, "rg-7b187484+sl-37b5d948", "no", true);
        check(s.blocked(2).indexOf("restart") >= 0, "set not running this boot: " + s.blocked(2));
        javaSet(root, "rg-7b187484+sl-37b5d948", "yes", true);
        Files.write(root.resolve("mnt/app/carplaymaps/HMI_BOOT"),
                "rg-7b187484+sl-11111111 a.jar b.jar\n".getBytes(StandardCharsets.US_ASCII));
        check(s.blocked(2) != null, "HMI_BOOT changed after boot: last-boot differs");
        javaSet(root, "rg-7b187484+sl-37b5d948", "yes", true);
        Files.write(root.resolve("mnt/persist/pmcp/DISABLED"), new byte[0]);
        check(s.blocked(2).indexOf("rescue") >= 0, "rescue card switch");
        Files.delete(root.resolve("mnt/persist/pmcp/DISABLED"));
        check(s.blocked(1) == null && s.hint().startsWith("Applies"), "all allowed, hint");
        check(SpeedLimitSetting.hasPackage("nai-1+np-2+rg-3+zoom-4+dn-5+sl-6", "sl"), "set parse last");
        check(!SpeedLimitSetting.hasPackage("slx-6", "sl") && !SpeedLimitSetting.hasPackage("sl", "rg"), "set parse");
    }

    // ---------------------------------------------------------------- the page

    static final class Tree {
        View view;
        WidgetList list;
        WidgetCloneFactory factory;
        WidgetCloneable factoryCloned;   // last source the factory clone factory was asked for
        WidgetModel[] viewChildren;
        WidgetModel[] listChildren;
    }

    static TextArea text(String name, int id) {
        TextArea t = new TextArea();
        t.set_name(name);
        t.set_targetId(id);
        return t;
    }

    static CommonImage image(String name, int id, int w, int h) {
        CommonImage i = new CommonImage();
        i.set_name(name);
        i.set_targetId(id);
        i.set_width(w);
        i.set_height(h);
        return i;
    }

    static Tree tree(String viewName, int width, int height, boolean withSelector) {
        Tree t = new Tree();
        View view = new View();
        view.set_name(viewName);
        view.set_targetId(1);
        view.set_width(width);
        view.set_height(height);
        Container headline = new Container();
        headline.set_name("headline");
        headline.set_targetId(SettingsPage.ID_HEADLINE);
        Button back = new Button();
        back.set_name("BackButton");
        headline.setChildren(new WidgetModel[] {text("TextLabel", 501), back});

        WidgetList list = new WidgetList();
        list.set_name("WidgetList");
        list.set_targetId(SettingsPage.ID_SETUP_LIST);
        list.set_height(549);
        t.factory = new WidgetCloneFactory() {
            public WidgetCloneable createWidgetCloneable(WidgetCloneable source) {
                t.factoryCloned = source;
                return null;
            }

            public void destroyWidgetCloneable(WidgetCloneable clone) {
            }
        };
        list.setWidgetCloneFactory(t.factory);

        ListItem plainItem = new ListItem();
        plainItem.set_name("SelectDevice");
        Button plain = new Button();
        plain.set_name("Button");
        plain.set_targetId(SettingsPage.ID_PLAIN_ENTRY);
        plain.setChildren(new WidgetModel[] {image("ScaleImage", 502, 1139, 80), text("TextLabel", 101603979)});
        plainItem.setChildren(new WidgetModel[] {plain});

        WidgetList options = new WidgetList();
        options.set_name("DropDownList");
        ListItem optionItem = new ListItem();
        Button option = new Button();
        option.setChildren(new WidgetModel[] {text("RowLabel", 503)});
        optionItem.setChildren(new WidgetModel[] {option});
        options.setChildren(new WidgetModel[] {optionItem});
        DropDown dropDown = new DropDown();
        dropDown.set_name("DropDown");
        dropDown.set_dropDownListRef(options);
        // on the unit the skin supplies these (cloneTree copies them); fewer than 5 skips the arrow adjustment
        dropDown.set_compositeBackgroundImages(new de.vw.mib.graphics.image.Image[0]);
        dropDown.setChildren(new WidgetModel[] {options});
        InactiveArea touch = new InactiveArea();
        touch.set_name("InactiveArea");

        ListItem selectorItem = new ListItem();
        DropDownButton selector = new DropDownButton();
        selector.set_name("DropDownButton");
        selector.set_targetId(withSelector ? SettingsPage.ID_SELECTOR : 999);
        Container arrow = new Container();
        arrow.set_name("ArrowGlowContainer");
        selector.setChildren(new WidgetModel[] {image("ScaleImage", 504, 1139, 80), text("TextLabel", 505),
            text("CurrentConnectiontype", 506), arrow, image("Separator", 507, 2, 80)});
        selector.set_dropDownRef(dropDown);
        selector.set_inactiveAreaRef(touch);
        selectorItem.setChildren(new WidgetModel[] {selector});
        list.setChildren(new WidgetModel[] {plainItem, selectorItem});

        Container popup = new Container();
        popup.set_name("MirrorlinkNotificationPopup");
        popup.setChildren(new WidgetModel[] {image("ScaleImage", SettingsPage.ID_GREY_BAR, 1139, 80)});
        view.setChildren(new WidgetModel[] {image("BackgroundImage", SettingsPage.ID_BACKGROUND, 1280, 640), headline,
            image("Frame", SettingsPage.ID_FRAME, 1280, 16), list, dropDown, touch, popup});
        t.view = view;
        t.list = list;
        t.viewChildren = view.getChildren();
        t.listChildren = list.getChildren();
        return t;
    }

    static void hookEnv(String name) throws Exception {
        MenuHook.resetForTest();
        Path root = unit(name);
        MenuHook.root = root.toString();
        MenuHook.offSwitch = root.resolve("pmcp-ui-off").toString();
        javaSet(root, "rg-7b187484+sl-37b5d948+ui-12345678", "trial", true);
    }

    /** As the factory: setup() then init(false); lifecycle CREATED -> INITIALIZED. */
    static void start(Object handler) throws Exception {
        HostRuntime.call(handler, "setup");
        HostRuntime.init(handler);
    }

    static void factoryState(Tree t, String what) {
        check(t.view.getChildren() == t.viewChildren || Arrays.equals(t.view.getChildren(), t.viewChildren),
                what + ": view children are the factory ones");
        check(Arrays.equals(t.list.getChildren(), t.listChildren), what + ": list children are the factory ones");
        check(((TemplateListModel) t.list).getWidgetCloneFactory() == t.factory, what + ": factory clone factory");
    }

    static void pageLifecycle() throws Exception {
        hookEnv("page");
        Tree t = tree("SMI_SETUP_MAIN", 1280, 640, true);
        Object handler = HostRuntime.createdHandler(t.view);
        start(handler);
        check(MenuHook.attachedCount() == 1, "attached at the start of init(), before View.init");
        SettingsPage page = MenuHook.pageOf((de.vw.mib.view.internal.AbstractViewHandler) handler);
        WidgetModel[] vc = t.view.getChildren();
        check(vc.length == t.viewChildren.length + 2, "view gets page and popup");
        for (int i = 0; i < t.viewChildren.length; i++) check(vc[i] == t.viewChildren[i], "factory view child kept " + i);
        WidgetModel[] lc = t.list.getChildren();
        check(lc.length == 3 && lc[0] == t.listChildren[0] && lc[1] == t.listChildren[1], "factory entries kept");
        check(lc[2] == page.entry(), "our entry appended last");
        check(((TemplateListModel) t.list).getWidgetCloneFactory() != t.factory, "entry clone factory installed");
        check(SettingsPage.findId(t.view, SettingsPage.ID_SELECTOR).getParent() == t.listChildren[1], "selector untouched");

        check(page.isAttached(), "factory View.init ran over our widgets");
        // the setup list clones our entry while scrolling: the clone gets a listener, which goes with the clone
        int listenersBefore = page.listenerCount();
        WidgetCloneFactory cf = ((TemplateListModel) t.list).getWidgetCloneFactory();
        WidgetCloneable clone = cf.createWidgetCloneable((WidgetCloneable) page.entry());
        check(clone != null && clone != page.entry() && page.listenerCount() == listenersBefore + 1, "entry clone with listener");
        cf.destroyWidgetCloneable(clone);
        check(page.listenerCount() == listenersBefore, "destroyed clone drops its listener");
        HostRuntime.call(handler, "activate");
        check(!page.isPageVisible() && !page.isPopupVisible(), "activate: factory list shown");
        check("Before street name".equals(page.rowValue(1)) || "Off".equals(page.rowValue(1)), "row value " + page.rowValue(1));
        check("Off".equals(page.rowValue(1)), "no file shows Off");

        page.action(SettingsPage.ACTION_OPEN);
        check(page.isPageVisible() && page.noteText().startsWith("Applies"), "page open, hint: " + page.noteText());
        page.action(SettingsPage.ACTION_ROW + 1);
        check(page.isPopupVisible(), "row opens the choices");
        page.action(SettingsPage.ACTION_CHOICE + 1);
        check(!page.isPopupVisible(), "choice closes the popup");
        Path root = Path.of(MenuHook.root);
        check("turnto\n".equals(bytes(mode(root))), "turnto saved from the page");
        check("Before street name".equals(page.rowValue(1)), "row shows the new value");
        check(page.noteText().startsWith("Saved"), "note after save: " + page.noteText());
        // blocked choice: rg missing
        javaSet(root, "sl-37b5d948+ui-12345678", "trial", true);
        page.action(SettingsPage.ACTION_ROW + 1);
        page.action(SettingsPage.ACTION_CHOICE + 1);
        check(!page.isPopupVisible() && page.noteText().indexOf("rg") >= 0, "blocked choice: reason " + page.noteText());
        page.action(SettingsPage.ACTION_ROW + 1);
        page.action(SettingsPage.ACTION_CHOICE + 2);
        check("street\n".equals(bytes(mode(root))), "street saved");
        // a choice index beyond the setting, a stray code and dismiss do nothing
        page.action(SettingsPage.ACTION_ROW + 1);
        page.action(SettingsPage.ACTION_CHOICE + 5);
        check(page.isPopupVisible() && "street\n".equals(bytes(mode(root))), "unused option slot ignored");
        page.action(SettingsPage.ACTION_DISMISS);
        check(!page.isPopupVisible(), "dismiss");
        page.action(12345);
        page.action(SettingsPage.ACTION_BACK);
        check(!page.isPageVisible(), "back closes the page");
        // a broken setting must not escape action()
        Files.createDirectories(root.resolve("ramdisk/pmcp-speedlimit.lock"));
        page.action(SettingsPage.ACTION_OPEN);
        page.action(SettingsPage.ACTION_ROW + 1);
        page.action(SettingsPage.ACTION_CHOICE);
        check(page.noteText().startsWith("Busy") && "street\n".equals(bytes(mode(root))), "busy shown, nothing written");
        Files.delete(root.resolve("ramdisk/pmcp-speedlimit.lock"));
        // second activation starts from the factory list again
        HostRuntime.setLifeCycle(handler, 3);
        HostRuntime.call(handler, "activate");
        check(!page.isPageVisible(), "re-activate hides the page");

        HostRuntime.setLifeCycle(handler, 3);
        HostRuntime.call(handler, "deinit");
        check(MenuHook.attachedCount() == 0 && !page.isAttached(), "deinit detaches");
        factoryState(t, "after deinit");
        check(t.view.getChildren() == t.viewChildren, "exact factory view array back");
        // the factory may run deinit -> init again without a new setup (screen-area zoom paths): the page comes back
        HostRuntime.setLifeCycle(handler, 2);
        HostRuntime.init(handler);
        check(MenuHook.attachedCount() == 1, "deinit -> init without setup: attached again");
        HostRuntime.call(handler, "activate");
        HostRuntime.call(handler, "deactivate");
        HostRuntime.call(handler, "deinit");
        factoryState(t, "after the second deinit");
        HostRuntime.setLifeCycle(handler, 1);
        HostRuntime.call(handler, "destroy");
        factoryState(t, "after destroy");
        // setup again (view reused after teardown): a fresh page
        HostRuntime.setLifeCycle(handler, 1);
        start(handler);
        check(MenuHook.attachedCount() == 1, "attached again after a new setup");
        HostRuntime.setLifeCycle(handler, 3);
        HostRuntime.call(handler, "deinit");
        factoryState(t, "after second deinit");
        check(readLog().indexOf("PAGE_DETACHED failures=0") >= 0, "clean detach logged");
    }

    static void missingDonorKeepsFactory() throws Exception {
        hookEnv("missing");
        Tree t = tree("SMI_SETUP_MAIN", 1280, 640, false);
        Object handler = HostRuntime.createdHandler(t.view);
        start(handler);
        check(MenuHook.attachedCount() == 0, "no attach without the selector donor");
        factoryState(t, "missing donor");
        check(t.view.getChildren() == t.viewChildren, "view array not even replaced");
        check(readLog().indexOf("Missing stock template 40267630") >= 0, "reason logged");
        HostRuntime.setLifeCycle(handler, 3);
        HostRuntime.call(handler, "activate");
        HostRuntime.setLifeCycle(handler, 3);
        HostRuntime.call(handler, "deinit");
        factoryState(t, "missing donor after lifecycle");

        hookEnv("canvas");
        Tree small = tree("SMI_SETUP_MAIN", 800, 480, true);
        handler = HostRuntime.createdHandler(small.view);
        start(handler);
        check(MenuHook.attachedCount() == 0, "800x480 canvas refused");
        factoryState(small, "800x480");
    }

    static void otherViewsUntouched() throws Exception {
        hookEnv("other");
        Tree t = tree("SYSTEM_SETUP_UNITS", 1280, 640, true);
        Object handler = HostRuntime.createdHandler(t.view);
        start(handler);
        check(MenuHook.attachedCount() == 0, "other view not attached");
        factoryState(t, "other view");
        HostRuntime.setLifeCycle(handler, 3);
        HostRuntime.call(handler, "activate");
        HostRuntime.fatal(handler, new IllegalStateException("not ours"));
        check(!new File(MenuHook.offSwitch).exists(), "failure of another view does not switch us off");
    }

    static void offSwitchAndFailure() throws Exception {
        hookEnv("off");
        Files.write(Path.of(MenuHook.offSwitch), new byte[0]);
        Tree t = tree("SMI_SETUP_MAIN", 1280, 640, true);
        Object handler = HostRuntime.createdHandler(t.view);
        start(handler);
        check(MenuHook.attachedCount() == 0, "off switch keeps the view factory");
        factoryState(t, "off switch");

        hookEnv("failure");
        Tree a = tree("SMI_SETUP_MAIN", 1280, 640, true);
        Object h1 = HostRuntime.createdHandler(a.view);
        start(h1);
        check(MenuHook.attachedCount() == 1, "attached before the failure");
        HostRuntime.call(h1, "activate");
        SettingsPage p1 = MenuHook.pageOf((de.vw.mib.view.internal.AbstractViewHandler) h1);
        // an entry clone alive (the list scrolled), then a lifecycle error: the factory fatalError only logs and goes on
        WidgetCloneFactory cf = ((TemplateListModel) a.list).getWidgetCloneFactory();
        int listeners = p1.listenerCount();
        WidgetCloneable alive = cf.createWidgetCloneable((WidgetCloneable) p1.entry());
        check(p1.listenerCount() == listeners + 1, "entry clone alive before the failure");
        HostRuntime.fatal(h1, new IllegalStateException("lifecycle error in our view"));
        check(new File(MenuHook.offSwitch).exists(), "failure sets the off switch");
        check(MenuHook.attachedCount() == 1 && p1.isAttached(), "failure leaves the page in the tree until deinit");
        check(((TemplateListModel) a.list).getWidgetCloneFactory() == cf, "our clone factory stays for the factory teardown");
        check(readLog().indexOf("lifecycle error in our view") >= 0, "stack logged");
        // the factory teardown destroys the clone through the list's clone factory: still ours, no NPE on clone data
        cf.destroyWidgetCloneable(alive);
        check(p1.listenerCount() == listeners, "clone destroyed by our factory after the failure");
        HostRuntime.setLifeCycle(h1, 3);
        HostRuntime.call(h1, "deinit");
        check(MenuHook.attachedCount() == 0 && !p1.isAttached(), "end-of-deinit hook detaches after the failure");
        factoryState(a, "detached after failure");
        check(readLog().lastIndexOf("PAGE_DETACHED failures=0") > readLog().indexOf("lifecycle error in our view"),
                "clean detach after the failure");
        HostRuntime.setLifeCycle(h1, 1);
        HostRuntime.call(h1, "destroy");
        factoryState(a, "after destroy");
        Tree b = tree("SMI_SETUP_MAIN", 1280, 640, true);
        Object h2 = HostRuntime.createdHandler(b.view);
        start(h2);
        check(MenuHook.attachedCount() == 0, "no new page after a failure");
        factoryState(b, "after failure");
        MenuHook.resetForTest();

        // our entry clone fails (any Throwable): the list gets a factory clone of the factory entry, nothing thrown
        hookEnv("clonefail");
        Tree c = tree("SMI_SETUP_MAIN", 1280, 640, true);
        Object h3 = HostRuntime.createdHandler(c.view);
        start(h3);
        SettingsPage p3 = MenuHook.pageOf((de.vw.mib.view.internal.AbstractViewHandler) h3);
        WidgetCloneFactory cf3 = ((TemplateListModel) c.list).getWidgetCloneFactory();
        int before = p3.listenerCount();
        SettingsPage.failCloneForTest = true;
        WidgetCloneable fallback;
        try {
            fallback = cf3.createWidgetCloneable((WidgetCloneable) p3.entry());
        } finally {
            SettingsPage.failCloneForTest = false;
        }
        check(c.factoryCloned != null && c.factoryCloned != p3.entry() && Arrays.asList(c.listChildren).contains(c.factoryCloned)
                && p3.listenerCount() == before, "clone failure: the factory clones the factory entry instead");
        check(new File(MenuHook.offSwitch).exists() && readLog().indexOf("ENTRY_CLONE_FAILED") >= 0, "clone failure: off switch, logged");
        cf3.destroyWidgetCloneable(fallback);
        HostRuntime.setLifeCycle(h3, 3);
        HostRuntime.call(h3, "deinit");
        factoryState(c, "after a clone failure");
        Tree d = tree("SMI_SETUP_MAIN", 1280, 640, true);
        start(HostRuntime.createdHandler(d.view));
        check(MenuHook.attachedCount() == 0, "no page after a clone failure");
        MenuHook.resetForTest();
    }

    // ---------------------------------------------------------------- Changes: Save (= GEM 5. Confirm)

    static void trialSave() throws Exception {
        Path root = unit("trial");
        Path p = root.resolve("mnt/persist/pmcp");
        TrialSetting t = new TrialSetting(root.toString());
        check(t.blocked(0) != null && "Saved".equals(t.valueText()) && t.hint() == null, "nothing installed: nothing to save");
        // Java set in its trial start (lsd.sh: trial marker + last-boot use=trial)
        javaSet(root, "rg-7b187484+ui-12345678", "trial", false);
        Files.write(p.resolve("trial.rg-7b187484+ui-12345678"), new byte[0]);
        check(t.blocked(0) == null && t.valueText().startsWith("Not saved") && t.hint() != null, "trial start: save offered");
        SpeedLimitSetting sl = new SpeedLimitSetting(root.toString());
        javaSet(root, "rg-7b187484+sl-37b5d948+ui-12345678", "trial", false);
        Files.write(p.resolve("trial.rg-7b187484+sl-37b5d948+ui-12345678"), new byte[0]);
        check(sl.blocked(1).indexOf("Changes") >= 0, "speed limit points at Changes: " + sl.blocked(1));
        check(t.select(0).startsWith("Saved") && Files.exists(p.resolve("ok.rg-7b187484+sl-37b5d948+ui-12345678")), "save writes ok.SET");
        check(bytes(p.resolve("boot.log")).indexOf("page-ok set=rg-7b187484+sl-37b5d948+ui-12345678") >= 0, "boot.log records the page save");
        check(sl.blocked(1) == null, "speed limit allowed after the save");
        check(t.blocked(0) != null && "Saved".equals(t.valueText()), "saved: nothing more to save");
        check(error(t) != null, "second save refused");
        // a factory start after a failed trial (use=no) can never be saved
        javaSet(root, "nai-11111111+ui-12345678", "no", false);
        Files.write(p.resolve("trial.nai-11111111+ui-12345678"), new byte[0]);
        check(t.blocked(0) != null, "use=no: no save");
        // the trial marker without this start's last-boot (set changed after the boot): no save
        javaSet(root, "nai-11111111+ui-12345678", "trial", false);
        Files.write(root.resolve("mnt/app/carplaymaps/HMI_BOOT"), "nai-22222222+ui-12345678 x.jar\n".getBytes(StandardCharsets.US_ASCII));
        check(t.blocked(0) != null, "HMI_BOOT changed after the boot: no save");
        // rescue card: never saved from the page
        javaSet(root, "nai-11111111+ui-12345678", "trial", false);
        Files.write(p.resolve("DISABLED"), new byte[0]);
        check(t.blocked(0).indexOf("rescue") >= 0 && "Off (rescue card)".equals(t.valueText()), "rescue card: no save");
        Files.delete(p.resolve("DISABLED"));
        // Android Auto trial (persist marker + this start's RAM marker), Java already saved
        Files.write(p.resolve("ok.nai-11111111+ui-12345678"), new byte[0]);
        Files.createDirectories(root.resolve("mnt/app/carplaymaps/aa"));
        Files.write(root.resolve("mnt/app/carplaymaps/aa/AA_BOOT"), "gamma-aaaaaaaa-bbbbbbbb-cccccccc\n".getBytes(StandardCharsets.US_ASCII));
        Files.write(p.resolve("aa-trial.gamma-aaaaaaaa-bbbbbbbb-cccccccc"), new byte[0]);
        Files.write(p.resolve("aa-ok.gamma-old"), new byte[0]);
        check(t.blocked(0) != null, "AA trial used in an earlier start (no RAM marker): no save");
        Files.write(root.resolve("ramdisk/pmcp-aa-trial.gamma-aaaaaaaa-bbbbbbbb-cccccccc"), new byte[0]);
        check(t.blocked(0) == null, "AA trial start: save offered");
        t.select(0);
        check(Files.exists(p.resolve("aa-ok.gamma-aaaaaaaa-bbbbbbbb-cccccccc")) && !Files.exists(p.resolve("aa-ok.gamma-old")),
                "AA save: aa-ok of this set only");
        // AA installed, phone not connected yet: no AA trial, the row does not claim "Saved"
        Path q = root.resolve("mnt/persist/pmcp");
        Files.write(root.resolve("mnt/app/carplaymaps/aa/AA_BOOT"), "gamma-dddddddd-eeeeeeee-ffffffff\n".getBytes(StandardCharsets.US_ASCII));
        check(t.valueText().startsWith("Android Auto: connect") && t.blocked(0).indexOf("phone") >= 0, "AA waiting for the phone: " + t.valueText());
        Files.write(q.resolve("aa-trial.gamma-dddddddd-eeeeeeee-ffffffff"), new byte[0]);
        check("Android Auto not saved".equals(t.valueText()), "AA trial used in an earlier start: not saved");
        // both trials in one start: one Save confirms both
        javaSet(root, "np-33333333+ui-12345678", "trial", false);
        Files.write(q.resolve("trial.np-33333333+ui-12345678"), new byte[0]);
        Files.write(root.resolve("ramdisk/pmcp-aa-trial.gamma-dddddddd-eeeeeeee-ffffffff"), new byte[0]);
        t.select(0);
        check(Files.exists(q.resolve("ok.np-33333333+ui-12345678")) && Files.exists(q.resolve("aa-ok.gamma-dddddddd-eeeeeeee-ffffffff"))
                && "Saved".equals(t.valueText()), "both trials saved at once");
        // CarPlay-only save leaves the AA confirmation alone
        javaSet(root, "zoom-44444444+ui-12345678", "trial", false);
        Files.write(q.resolve("trial.zoom-44444444+ui-12345678"), new byte[0]);
        t.select(0);
        check(Files.exists(q.resolve("aa-ok.gamma-dddddddd-eeeeeeee-ffffffff")), "CarPlay-only save keeps aa-ok");
        // a set id that is not a plain name is never used as a file name
        Files.write(root.resolve("mnt/app/carplaymaps/HMI_BOOT"), "../x x.jar\n".getBytes(StandardCharsets.US_ASCII));
        check(t.javaPending() == null, "path-like set id ignored");
    }

    static String error(Setting s) {
        try {
            s.select(0);
            return null;
        } catch (Exception e) {
            return e.getMessage();
        }
    }

    static String readLog() throws Exception {
        return bytes(Path.of(UiLog.path));
    }
}
