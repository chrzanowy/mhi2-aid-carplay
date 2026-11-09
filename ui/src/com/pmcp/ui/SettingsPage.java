/*
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Based on org.omonob.cpmap.ui.IndependentMenuViewBridge from omonob/MHI2-Carplay-Maps (src/vc-menu, commit 5ba6f7f,
 * GPL-3.0), the "Virtual Cockpit settings" page in App-Connect > Settings. Changes for pmcp: only the 1280x640 VW skin
 * path (MU1161 HIGH_GP_VW_Skin_A), rows come from Setting objects, one note line under the rows instead of the
 * confirmation popup, a guarded detach that restores each part separately, and no font, profile or language tables.
 */
package com.pmcp.ui;

import de.vw.mib.widgets.Container;
import de.vw.mib.widgets.WidgetList;
import de.vw.mib.widgets.controller.DefaultInactiveAreaController;
import de.vw.mib.widgets.controller.DefaultListItemController;
import de.vw.mib.widgets.controller.DefaultPushButtonController;
import de.vw.mib.widgets.controller.DefaultPushUpController;
import de.vw.mib.widgets.controller.DefaultWidgetListController;
import de.vw.mib.widgets.event.OutEventListener;
import de.vw.mib.widgets.interfaces.WidgetCloneFactory;
import de.vw.mib.widgets.interfaces.WidgetCloneable;
import de.vw.mib.widgets.models.AbstractButtonModel;
import de.vw.mib.widgets.models.AbstractTextModel;
import de.vw.mib.widgets.models.ButtonModel;
import de.vw.mib.widgets.models.ContainerModel;
import de.vw.mib.widgets.models.DropDownButtonModel;
import de.vw.mib.widgets.models.DropDownModel;
import de.vw.mib.widgets.models.InactiveAreaModel;
import de.vw.mib.widgets.models.ListItemModel;
import de.vw.mib.widgets.models.PushUpModel;
import de.vw.mib.widgets.models.TemplateListModel;
import de.vw.mib.widgets.models.TextAreaModel;
import de.vw.mib.widgets.models.ViewModel;
import de.vw.mib.widgets.models.WidgetListModel;
import de.vw.mib.widgets.models.WidgetModel;
import de.vw.mib.widgets.ui.ContainerUI;
import de.vw.mib.widgets.ui.WidgetUI;
import java.lang.reflect.Array;
import java.lang.reflect.Method;
import java.util.Enumeration;
import java.util.Hashtable;
import java.util.Vector;

/**
 * A native-looking settings page laid over the factory App-Connect setup view (SMI_SETUP_MAIN). Nothing new is loaded
 * from the skin: every widget is a clone of a factory widget of the same view (found by its targetId), with our own
 * controllers and listeners. The factory widgets themselves are never changed, except two lists of children (the
 * setup list gets one more entry, the view gets the page and the popup) and the setup list's clone factory; detach puts
 * back exactly the original arrays and factory.
 *
 * Every lookup happens before the first change. A missing donor, an unexpected type or another canvas size throws in
 * the constructor and the view stays factory (MenuHook logs it).
 */
final class SettingsPage {
    // targetIds of the donors in Resources/skin1/viewhandler.zip:Ssm_5458.jxe (each present once, MU1161 and MU1367)
    static final int ID_SETUP_LIST = 47234883;     // WidgetList with the App-Connect setup entries
    static final int ID_GREY_BAR = 56030257;       // the visible grey bar image of a row (row width and height)
    static final int ID_SELECTOR = 40267630;       // DropDownButton "connection type" (row look, popup, touch layer)
    static final int ID_PLAIN_ENTRY = 4894361;     // button of the SelectDevice entry (our entry in the setup list)
    static final int ID_BACKGROUND = 69892873;     // view background image
    static final int ID_HEADLINE = 19482720;       // headline with title and back button
    static final int ID_FRAME = 96892073;          // line under the headline
    static final String ENTRY_TEXT = "CarPlay (pmcp)";
    static final int MAX_CHOICES = 6;
    static final int VIEW_WIDTH = 1280;
    static final int VIEW_HEIGHT = 640;
    static final int ROW_PITCH = 91;
    static final int PANEL_X = 30;
    static final int PANEL_Y = 84;
    static final int PANEL_HEIGHT = 549;

    static final int ACTION_ROW = 0;        // 0 .. rows-1
    static final int ACTION_CHOICE = 10;    // 10 .. 10+MAX_CHOICES-1
    static final int ACTION_DISMISS = 20;
    static final int ACTION_OPEN = 60;
    static final int ACTION_BACK = 61;
    static final int ACTION_PAGE_TOUCH = 90;

    private final Setting[] settings;
    private final ViewModel view;
    private final WidgetModel stockList;
    private final WidgetModel stockReference;
    private final WidgetModel[] originalStockChildren;
    private final WidgetModel[] originalViewChildren;
    private final WidgetCloneFactory originalCloneFactory;
    private final int stockHeight;

    /** Host test only (TestUi): makes our entry clone fail. */
    static boolean failCloneForTest;
    private final ListItemModel entryItem;
    private final WidgetModel entryDonor;
    private final TextAreaModel entryLabel;
    private final Vector entryClones = new Vector();
    private final Container page;
    private final Container panel;
    private final TextAreaModel pageTitle;
    private final TextAreaModel note;
    private final ButtonModel[] rows;
    private final TextAreaModel[] names;
    private final TextAreaModel[] values;

    private final Container popup;
    private final DropDownModel popupBackground;
    private final WidgetList choiceList;
    private final ListItemModel[] choiceItems = new ListItemModel[MAX_CHOICES];
    private final ButtonModel[] options = new ButtonModel[MAX_CHOICES];
    private final TextAreaModel[] optionLabels = new TextAreaModel[MAX_CHOICES];

    private final Vector listeners = new Vector();
    private final Hashtable cloneListeners = new Hashtable();
    private final Hashtable copies = new Hashtable();
    private int nextId = 1049000000;
    private int activeRow = -1;
    private String noteText = "";
    private boolean attached;

    SettingsPage(ViewModel target, Setting[] rowSettings) throws Exception {
        view = target;
        settings = rowSettings;
        if (view.get_width() != VIEW_WIDTH || view.get_height() != VIEW_HEIGHT) {
            throw new IllegalStateException(new StringBuffer("Unsupported canvas ").append(view.get_width()).append('x')
                    .append(view.get_height()).toString());
        }
        if (settings.length < 1 || settings.length * ROW_PITCH > PANEL_HEIGHT - 120) {
            throw new IllegalStateException("Row count");
        }
        for (int i = 0; i < settings.length; i++) {
            if (settings[i].count() < 1 || settings[i].count() > MAX_CHOICES) {
                throw new IllegalStateException("Choice count");
            }
        }

        // ---- every factory lookup first, nothing changed yet ----
        stockList = required(view, ID_SETUP_LIST);
        if (!(stockList instanceof WidgetListModel) || !(stockList instanceof TemplateListModel)) {
            throw new IllegalStateException("Setup list type");
        }
        stockReference = required(view, ID_GREY_BAR);
        originalStockChildren = ((ContainerModel) stockList).getChildren();
        originalViewChildren = view.getChildren();
        if (originalStockChildren == null || originalViewChildren == null) {
            throw new IllegalStateException("Factory children missing");
        }
        originalCloneFactory = ((TemplateListModel) stockList).getWidgetCloneFactory();
        if (originalCloneFactory == null) {
            throw new IllegalStateException("Native list clone factory missing");
        }
        stockHeight = stockList.get_height();
        WidgetModel rowDonor = required(view, ID_SELECTOR);
        if (!(rowDonor instanceof DropDownButtonModel) || !(rowDonor instanceof ButtonModel)) {
            throw new IllegalStateException("Selector type");
        }
        WidgetModel plainDonor = required(view, ID_PLAIN_ENTRY);
        DropDownModel dropDownDonor = ((DropDownButtonModel) rowDonor).get_dropDownRef();
        if (dropDownDonor == null || dropDownDonor.get_dropDownListRef() == null) {
            throw new IllegalStateException("OEM DropDown template missing");
        }
        if (!(dropDownDonor.get_dropDownListRef() instanceof WidgetList)) {
            throw new IllegalStateException("OEM DropDown list type");
        }
        InactiveAreaModel touchDonor = ((DropDownButtonModel) rowDonor).get_inactiveAreaRef();
        if (touchDonor == null) {
            throw new IllegalStateException("OEM inactive area missing");
        }
        WidgetModel itemDonor = findListItem(dropDownDonor.get_dropDownListRef());
        if (itemDonor == null || findButton(itemDonor) == null || find(findButton(itemDonor), "RowLabel") == null) {
            throw new IllegalStateException("OEM list item template missing");
        }
        entryDonor = ancestorListItem(plainDonor);
        if (!(entryDonor instanceof WidgetCloneable)) {
            throw new IllegalStateException("Native entry type");
        }
        WidgetModel backgroundDonor = required(view, ID_BACKGROUND);
        WidgetModel headlineDonor = required(view, ID_HEADLINE);
        WidgetModel frameDonor = required(view, ID_FRAME);
        if (!(headlineDonor instanceof ContainerModel) || find(headlineDonor, "TextLabel") == null
                || findButton(headlineDonor) == null) {
            throw new IllegalStateException("Headline template");
        }

        // ---- clones (still detached from the factory tree) ----
        // One real native list entry appended to the setup list. The factory entries are not renamed, hidden or resized.
        entryItem = (ListItemModel) cloneTree(entryDonor);
        ButtonModel entryButton = findButton(entryItem);
        entryLabel = (TextAreaModel) find(entryButton, "TextLabel");
        if (entryLabel == null) {
            throw new IllegalStateException("Native entry label missing");
        }
        prepareStaticItem(entryItem, entryButton);
        geometry(entryItem, 30, 0, 1139, 94);
        geometry(entryButton, 0, 0, 1139, 94);
        geometry(entryLabel, 30, 23, 1024, 47);
        resizeBackground(entryButton);
        push(entryButton, ACTION_OPEN);

        page = container("PMCP_SETTINGS_PAGE", 0, 0, VIEW_WIDTH, VIEW_HEIGHT);
        WidgetModel background = cloneTree(backgroundDonor);
        geometry(background, 0, 0, VIEW_WIDTH, VIEW_HEIGHT);
        // Full-screen layer under the rows: a touch outside them must not reach the factory widgets below the page.
        InactiveAreaModel pageTouch = (InactiveAreaModel) cloneTree(touchDonor);
        geometry(pageTouch, 0, 0, VIEW_WIDTH, VIEW_HEIGHT);
        pageTouch.set_exclusionArea(new de.vw.mib.graphics.Rectangle());
        DefaultInactiveAreaController pageTouchController = new DefaultInactiveAreaController();
        pageTouch.setController(pageTouchController);
        pageTouchController.setWidget(pageTouch);
        listen(pageTouch, pageTouchController, ACTION_PAGE_TOUCH);
        ContainerModel headline = (ContainerModel) cloneTree(headlineDonor);
        pageTitle = (TextAreaModel) find(headline, "TextLabel");
        push(findButton(headline), ACTION_BACK);
        WidgetModel frame = cloneTree(frameDonor);
        geometry(frame, 0, 82, VIEW_WIDTH, 16);
        panel = container("PMCP_SETTINGS_ROWS", PANEL_X, PANEL_Y, 1139, PANEL_HEIGHT);
        rows = new ButtonModel[settings.length];
        names = new TextAreaModel[settings.length];
        values = new TextAreaModel[settings.length];
        WidgetModel[] panelNodes = new WidgetModel[settings.length + 1];
        for (int i = 0; i < settings.length; i++) {
            rows[i] = (ButtonModel) cloneTree(rowDonor);
            names[i] = (TextAreaModel) find(rows[i], "TextLabel");
            values[i] = (TextAreaModel) find(rows[i], "CurrentConnectiontype");
            if (names[i] == null || values[i] == null) {
                throw new IllegalStateException("Exact selector labels missing");
            }
            // The native selector look with our own push event and popup; no link to the factory state machine.
            ((DropDownButtonModel) rows[i]).set_dropDownRef(null);
            ((DropDownButtonModel) rows[i]).set_inactiveAreaRef(null);
            ((DropDownButtonModel) rows[i]).set_openDropDown(false);
            geometry(rows[i], 0, i * ROW_PITCH, 1139, stockReference.get_height());
            push(rows[i], ACTION_ROW + i);
            panelNodes[i] = rows[i];
        }
        note = (TextAreaModel) cloneTree(entryLabel);
        normalizeText(note, 100, true);
        panelNodes[settings.length] = note;
        panel.setChildren(panelNodes);
        page.setChildren(new WidgetModel[] {background, pageTouch, frame, (WidgetModel) headline, panel});
        page.set_visible(false);

        popup = container("PMCP_CHOICE_POPUP", 0, 0, VIEW_WIDTH, VIEW_HEIGHT);
        InactiveAreaModel dismiss = (InactiveAreaModel) cloneTree(touchDonor);
        geometry(dismiss, 0, 0, VIEW_WIDTH, VIEW_HEIGHT);
        dismiss.set_exclusionArea(new de.vw.mib.graphics.Rectangle());
        DefaultInactiveAreaController dismissController = new DefaultInactiveAreaController();
        dismiss.setController(dismissController);
        dismissController.setWidget(dismiss);
        listen(dismiss, dismissController, ACTION_DISMISS);
        // The complete native DropDown graph (skin, insets, option pitch), never a stretched button.
        popupBackground = (DropDownModel) cloneTree(dropDownDonor);
        popupBackground.set_name("PMCP_DROPDOWN");
        popupBackground.set_closeAutomatically(false);
        popupBackground.set_closeMode(PushUpModel.CLOSEMODE_IMMEDIATE);
        DefaultPushUpController popupController = new DefaultPushUpController();
        popupBackground.setController(popupController);
        popupController.setWidget(popupBackground);
        choiceList = (WidgetList) popupBackground.get_dropDownListRef();
        choiceList.set_name("PMCP_CHOICES");
        choiceList.setListControl(null);
        choiceList.setListItemTransfer(null);
        choiceList.set_cursorImageRef(null);
        choiceList.set_followItemRefs(null);
        choiceList.set_letterScrollingIndicatorRef(null);
        choiceList.set_letterScrollingTextRef(null);
        choiceList.set_listControlEnabled(false);
        choiceList.set_followMode(false);
        choiceList.set_dragDropEnabled(false);
        choiceList.set_letterScrollingEnabled(false);
        choiceList.set_listViewObserverEnabled(false);
        choiceList.set_dynamicItemSize(false);
        choiceList.set_cyclicScrolling(false);
        choiceList.set_interactive(true);
        choiceList.set_orientation(WidgetListModel.ORIENTATION_VERTICAL);
        choiceList.set_scrollTypeTouch(TemplateListModel.SCROLLTYPETOUCH_STEPLESS);
        choiceList.set_scrollTypeRotary(TemplateListModel.SCROLLTYPEROTARY_LAST_ELEMENT);
        choiceList.set_forwardPressDelay(120);
        choiceList.set_padding(new de.vw.mib.graphics.Insets(0, 0, 0, 0));
        choiceList.set_spacingVertical(-3);
        choiceList.set_spacingHorizontal(0);
        choiceList.set_spacingPage(0);
        choiceList.set_separatorMode(WidgetListModel.SEPARATOR_MODE_ENABLED);
        geometry(choiceList, 26, 23, 562, PANEL_HEIGHT);
        DefaultWidgetListController listController = new DefaultWidgetListController();
        choiceList.setController(listController);
        listController.setWidget(choiceList);
        WidgetModel[] itemNodes = new WidgetModel[MAX_CHOICES];
        for (int i = 0; i < MAX_CHOICES; i++) {
            choiceItems[i] = (ListItemModel) cloneTree(itemDonor);
            options[i] = findButton(choiceItems[i]);
            optionLabels[i] = (TextAreaModel) find(options[i], "RowLabel");
            if (optionLabels[i] == null) {
                throw new IllegalStateException("Native option label missing");
            }
            geometry(options[i], 0, 0, 562, 94);
            push(options[i], ACTION_CHOICE + i);
            choiceItems[i].set_name("PMCP_CHOICE_ITEM");
            choiceItems[i].setListItemControl(null);
            choiceItems[i].set_dynamicIndex(-1);
            choiceItems[i].set_existenceFlags(null);
            choiceItems[i].set_subItemRefs(null);
            choiceItems[i].set_dummyContentRef(null);
            choiceItems[i].set_effectWidgetRefs(null);
            choiceItems[i].set_dynamicResizeWidgetRef(null);
            choiceItems[i].set_dynamicResizeDirection(ListItemModel.DYNAMICRESIZEDIRECTION_NONE);
            choiceItems[i].set_numberContainerRef(null);
            choiceItems[i].set_numberTextRef(null);
            choiceItems[i].set_selectable(true);
            choiceItems[i].set_draggable(false);
            choiceItems[i].set_lockable(false);
            choiceItems[i].set_selectedButtonRefs(new AbstractButtonModel[] {options[i]});
            // The saved value belongs to the Setting, not to an ASL list: rotary focus (selected) and the current-value
            // mark (activated) stay separate.
            choiceItems[i].set_activatedButtonRefs(new AbstractButtonModel[0]);
            choiceItems[i].set_activatedIndex(-1);
            geometry(choiceItems[i], 0, i * ROW_PITCH, 562, 94);
            DefaultListItemController itemController = new DefaultListItemController();
            choiceItems[i].setController(itemController);
            itemController.setWidget(choiceItems[i]);
            itemNodes[i] = choiceItems[i];
        }
        choiceList.setChildren(itemNodes);
        popupBackground.setChildren(new WidgetModel[] {choiceList});
        popup.setChildren(new WidgetModel[] {dismiss, popupBackground});
        popup.set_visible(false);
        fill();
    }

    /**
     * The only changes to the factory tree, done last. Called from MenuHook at the start of AbstractViewHandler.init(),
     * before the factory View.init(): its initialization then builds list caches and touch delegation for our widgets
     * too, once, like for its own. If one of the three changes fails, the ones already done are undone.
     */
    void attach() {
        try {
            ((TemplateListModel) stockList).setWidgetCloneFactory(new EntryCloneFactory());
            ((ContainerModel) stockList).setChildren(append(originalStockChildren, entryItem));
            view.setChildren(append(append(originalViewChildren, page), popup));
            attached = true;
        } catch (Throwable error) {
            // also a LinkageError: never leave our clone factory or entry in a list that is not in MenuHook's table
            detach();
            throw new IllegalStateException(new StringBuffer("attach rolled back: ").append(error).toString());
        }
        UiLog.log(new StringBuffer("PAGE_ATTACHED rows=").append(settings.length)
                .append(" entries=").append(originalStockChildren.length).append("+1").toString());
    }

    /** Puts back the factory arrays and clone factory; each step on its own, so one failure does not skip the rest. */
    void detach() {
        int failures = 0;
        for (int i = 0; i < listeners.size(); i++) {
            if (!removeListener(listeners.elementAt(i))) {
                failures++;
            }
        }
        try {
            view.setChildren(originalViewChildren);
        } catch (Throwable error) {
            failures++;
            UiLog.log("DETACH_VIEW_FAILED", error);
        }
        try {
            ((ContainerModel) stockList).setChildren(originalStockChildren);
        } catch (Throwable error) {
            failures++;
            UiLog.log("DETACH_LIST_FAILED", error);
        }
        try {
            ((TemplateListModel) stockList).setWidgetCloneFactory(originalCloneFactory);
        } catch (Throwable error) {
            failures++;
            UiLog.log("DETACH_FACTORY_FAILED", error);
        }
        try {
            stockList.set_height(stockHeight);
        } catch (Throwable error) {
            failures++;
        }
        attached = false;
        UiLog.log(new StringBuffer("PAGE_DETACHED failures=").append(failures).toString());
    }

    private static boolean removeListener(Object listener) {
        try {
            Action action = (Action) listener;
            action.controller.removeOutEventListener(action);
            return true;
        } catch (Throwable error) {
            return false;
        }
    }

    /** AbstractViewHandler.activate() finished: the view is shown again, start from the factory list. */
    void activated() throws Exception {
        if (!attached) {
            return;
        }
        closePopup();
        page.set_visible(false);
        stockList.set_height(stockHeight);
        fill();
        ((WidgetListModel) stockList).validateList();
        entryItem.repaint();
    }

    int listenerCount() {
        return listeners.size();
    }

    boolean isAttached() {
        return attached;
    }

    boolean isPageVisible() {
        return page.is_visible();
    }

    boolean isPopupVisible() {
        return popup.is_visible();
    }

    String noteText() {
        return noteText;
    }

    String rowValue(int row) {
        return values[row].get_text();
    }

    ListItemModel entry() {
        return entryItem;
    }

    /** Texts and the geometry the factory layout may have changed during init/activate. */
    private void fill() {
        entryLabel.set_text(ENTRY_TEXT);
        entryLabel.set_alignmentHorizontal(AbstractTextModel.ALIGNMENTHORIZONTAL_LEFT);
        entryLabel.invalidate();
        pageTitle.set_text(ENTRY_TEXT);
        pageTitle.set_alignmentHorizontal(AbstractTextModel.ALIGNMENTHORIZONTAL_LEFT);
        pageTitle.invalidate();
        for (int i = 0; i < entryClones.size(); i++) {
            TextAreaModel label = (TextAreaModel) find((WidgetModel) entryClones.elementAt(i), "TextLabel");
            if (label != null) {
                label.set_text(ENTRY_TEXT);
                label.invalidate();
            }
        }
        int width = stockReference.get_width();
        int height = stockReference.get_height();
        if (PANEL_X + width > VIEW_WIDTH || width < 600 || height < 64 || height > 100) {
            throw new IllegalStateException("OEM grey-bar bounds invalid");
        }
        geometry(panel, PANEL_X, PANEL_Y, width, PANEL_HEIGHT);
        for (int i = 0; i < rows.length; i++) {
            geometry(rows[i], 0, i * ROW_PITCH, width, height);
            resizeBackground(rows[i]);
            names[i].set_x(30);
            names[i].set_width(510);
            values[i].set_x(600);
            values[i].set_width(447);
            WidgetModel arrow = find(rows[i], "ArrowGlowContainer");
            if (arrow != null) {
                arrow.set_x(1067);
            }
            WidgetModel separator = find(rows[i], "Separator");
            if (separator != null) {
                separator.set_x(569);
            }
            names[i].set_text(settings[i].label());
            values[i].set_text(valueText(settings[i]));
            names[i].set_alignmentHorizontal(AbstractTextModel.ALIGNMENTHORIZONTAL_LEFT);
            values[i].set_alignmentHorizontal(AbstractTextModel.ALIGNMENTHORIZONTAL_LEFT);
            names[i].invalidate();
            values[i].invalidate();
            rows[i].repaint();
        }
        geometry(note, 30, rows.length * ROW_PITCH + 20, width - 60, 100);
        note.set_alignmentHorizontal(AbstractTextModel.ALIGNMENTHORIZONTAL_LEFT);
        note.set_text(noteText);
        note.invalidate();
    }

    private static String valueText(Setting setting) {
        int current = setting.current();
        return current < 0 || current >= setting.count() ? setting.invalidText() : setting.choice(current);
    }

    private void setNote(String text) {
        noteText = text == null ? "" : text;
        note.set_text(noteText);
        note.invalidate();
    }

    private void openChoices(int row) {
        activeRow = row;
        Setting setting = settings[row];
        int count = setting.count();
        int current = setting.current();
        choiceList.set_visible(true);
        choiceList.set_height(count * ROW_PITCH + 3);
        popupBackground.set_height(count * ROW_PITCH + 50);
        for (int i = 0; i < MAX_CHOICES; i++) {
            boolean visible = i < count;
            boolean allowed = visible && setting.blocked(i) == null;
            // A disabled native widget passes its tap to the dismiss layer: keep it enabled, draw it grey and refuse
            // it in action() (and again in the Setting).
            choiceItems[i].set_visible(visible);
            options[i].set_visible(visible);
            options[i].set_enabled(true);
            options[i].set_selected(false);
            optionLabels[i].set_text(visible ? setting.choice(i) : "");
            optionLabels[i].set_alpha(allowed ? 255 : 96);
            optionLabels[i].invalidate();
            options[i].repaint();
        }
        // Visibility changes initialize the native list viewport: show first, then set the position.
        popup.set_visible(true);
        choiceList.validateList();
        if (current >= 0) {
            choiceList.setActivatedIndex(current);
            choiceList.set_selectedIndex(current);
        }
        popupBackground.set_layoutAutomatically(true);
        popupBackground.setAutoLayoutArea(new de.vw.mib.graphics.Rectangle(0, PANEL_Y, VIEW_WIDTH, PANEL_HEIGHT));
        de.vw.mib.graphics.Rectangle anchor = new de.vw.mib.graphics.Rectangle();
        rows[row].getAbsBounds(anchor);
        popupBackground.setArrowDestinationArea(anchor);
        popupBackground.set_visible(true);
        choiceList.setViewportY(0);
        for (int i = 0; i < count; i++) {
            options[i].set_activated(i == current);
        }
        popup.repaint();
        UiLog.log(new StringBuffer("CHOICES_OPEN row=").append(row).append(" current=").append(current).toString());
    }

    private void closePopup() {
        popupBackground.set_visible(false);
        popup.set_visible(false);
        activeRow = -1;
    }

    private void choose(int choice) {
        Setting setting = settings[activeRow];
        if (choice >= setting.count()) {
            return;
        }
        String reason = setting.blocked(choice);
        closePopup();
        if (reason != null) {
            setNote(reason);
            UiLog.log("CHOICE_BLOCKED", reason);
            return;
        }
        try {
            setNote(setting.select(choice));
        } catch (Throwable error) {
            String message = error.getMessage();
            setNote(message == null || message.length() == 0 ? "Not saved." : message);
            UiLog.log("SAVE_FAILED", error);
        }
        fill();
    }

    /** Every touch of our widgets ends here, on the HMI thread. Nothing thrown leaves it. */
    void action(int action) {
        try {
            if (action == ACTION_OPEN) {
                noteText = "";
                fill();
                setNote(settings[0].hint());
                page.set_visible(true);
                page.repaint();
                UiLog.log("PAGE_OPEN");
            } else if (action == ACTION_BACK) {
                closePopup();
                page.set_visible(false);
                UiLog.log("PAGE_CLOSE");
            } else if (action == ACTION_DISMISS) {
                closePopup();
            } else if (action >= ACTION_ROW && action < ACTION_ROW + rows.length) {
                fill();
                openChoices(action - ACTION_ROW);
            } else if (action >= ACTION_CHOICE && action < ACTION_CHOICE + MAX_CHOICES && activeRow >= 0) {
                choose(action - ACTION_CHOICE);
            }
        } catch (Throwable error) {
            UiLog.log("ACTION_FAILED", error);
            try {
                closePopup();
                setNote("Error, see /ramdisk/pmcp-ui.log.");
            } catch (Throwable ignored) {
                // the page stays as it is; Back still works
            }
        }
    }

    // ---- the setup list clones its entries (scrolling): ours is cloned here, the factory ones by the factory ----

    private final class EntryCloneFactory implements WidgetCloneFactory {
        public WidgetCloneable createWidgetCloneable(WidgetCloneable source) {
            if (source != entryItem) {
                return originalCloneFactory.createWidgetCloneable(source);
            }
            try {
                if (failCloneForTest) {
                    throw new LinkageError("host test");
                }
                ListItemModel item = (ListItemModel) cloneTree(entryItem);
                ButtonModel button = findButton(item);
                prepareStaticItem(item, button);
                cloneListeners.put(item, push(button, ACTION_OPEN));
                entryClones.addElement(item);
                return (WidgetCloneable) item;
            } catch (Throwable error) {
                // called by the factory list on the HMI thread (View.init, scrolling): never throw from here. Fallback:
                // a factory clone of the factory entry our entry was copied from (valid clone data, destroyed by the
                // factory); that row is a duplicate of a factory entry, and the page is off from the next start.
                UiLog.log("ENTRY_CLONE_FAILED factory entry instead, page off from the next start:", error);
                MenuHook.turnOff();
                return originalCloneFactory.createWidgetCloneable((WidgetCloneable) entryDonor);
            }
        }

        public void destroyWidgetCloneable(WidgetCloneable clone) {
            if (entryClones.removeElement(clone)) {
                try {
                    Object listener = cloneListeners.remove(clone);
                    if (listener != null) {
                        removeListener(listener);
                        listeners.removeElement(listener);
                    }
                } catch (Throwable error) {
                    UiLog.log("ENTRY_CLONE_DESTROY_FAILED", error);
                }
                return;
            }
            originalCloneFactory.destroyWidgetCloneable(clone);
        }
    }

    private final class Action implements OutEventListener {
        final de.vw.mib.widgets.controller.WidgetController controller;
        final int code;

        Action(de.vw.mib.widgets.controller.WidgetController owner, int value) {
            controller = owner;
            code = value;
        }

        public void outHMIEventFired(String event) {
            if ("released".equals(event)) {
                action(code);
            }
        }

        public void outIntegerEventFired(String event, int value) {
        }

        public void outBooleanEventFired(String event, boolean value) {
        }

        public void outStringEventFired(String event, String value) {
        }

        public void outPointEventFired(String event, int a, int b, int c, int d) {
        }

        public void outListItemEventFired(String event, int a, int b, int c, int d, String text, long number) {
        }

        public void outSpellerEventFired(String event, String text, int a, int b, int c) {
        }
    }

    private Action listen(WidgetModel widget, de.vw.mib.widgets.controller.WidgetController controller, int code) {
        Action listener = new Action(controller, code);
        controller.addOutEventListener(listener);
        listeners.addElement(listener);
        return listener;
    }

    private Action push(ButtonModel button, int code) {
        DefaultPushButtonController controller = new DefaultPushButtonController();
        button.setController(controller);
        controller.setWidget(button);
        button.set_predictiveActivation(false);
        button.set_buttonMode(ButtonModel.BUTTONMODE_DEFAULT);
        button.set_interactive(true);
        return listen(button, controller, code);
    }

    private static void prepareStaticItem(ListItemModel item, ButtonModel button) {
        item.setListItemControl(null);
        item.set_dynamicIndex(-1);
        item.set_existenceFlags(null);
        // The SelectDevice donor depends on a connected phone; our entry is always there and always works.
        item.set_visible(true);
        button.set_visible(true);
        item.set_enabled(true);
        button.set_enabled(true);
        button.set_interactive(true);
        item.set_availableInVariant(true);
        button.set_availableInVariant(true);
        item.set_subItemRefs(null);
        item.set_dummyContentRef(null);
        item.set_effectWidgetRefs(null);
        item.set_dynamicResizeWidgetRef(null);
        item.set_dynamicResizeDirection(ListItemModel.DYNAMICRESIZEDIRECTION_NONE);
        item.set_numberContainerRef(null);
        item.set_numberTextRef(null);
        item.set_activatedIndex(-1);
        item.set_selectable(true);
        item.set_draggable(false);
        item.set_lockable(false);
        item.set_selectedButtonRefs(new AbstractButtonModel[] {button});
        item.set_activatedButtonRefs(new AbstractButtonModel[0]);
        DefaultListItemController controller = new DefaultListItemController();
        item.setController(controller);
        controller.setWidget(item);
    }

    private Container container(String name, int x, int y, int w, int h) {
        Container result = new Container();
        ContainerUI ui = new ContainerUI();
        result.setUI(ui);
        ui.setWidget(result);
        result.set_name(name);
        result.set_targetId(nextId++);
        geometry(result, x, y, w, h);
        return result;
    }

    private static void geometry(WidgetModel widget, int x, int y, int w, int h) {
        widget.set_enabled(true);
        widget.set_visible(true);
        widget.set_availableInVariant(true);
        widget.set_layoutable(false);
        widget.set_alpha(255);
        widget.set_x(x);
        widget.set_y(y);
        widget.set_width(w);
        widget.set_height(h);
    }

    private static void normalizeText(TextAreaModel text, int height, boolean multiline) {
        text.set_height(height);
        text.set_baselineOffset(0);
        text.set_lineSpacing(0);
        text.set_padding(new de.vw.mib.graphics.Insets(0, 0, 0, 0));
        text.set_alignmentVertical(multiline ? TextAreaModel.ALIGNMENTVERTICAL_TOP : TextAreaModel.ALIGNMENTVERTICAL_CENTER);
        text.set_lineBreakMode(multiline ? TextAreaModel.LINEBREAKMODE_WORD : TextAreaModel.LINEBREAKMODE_NONE);
        text.set_visualLineCount(multiline ? 2 : 1);
    }

    private static void resizeBackground(ButtonModel button) {
        WidgetModel image = find(button, "ScaleImage");
        if (image != null) {
            geometry(image, 0, 0, button.get_width(), button.get_height());
        }
    }

    private static WidgetModel[] append(WidgetModel[] original, WidgetModel added) {
        WidgetModel[] result = new WidgetModel[original.length + 1];
        System.arraycopy(original, 0, result, 0, original.length);
        result[original.length] = added;
        return result;
    }

    private static ListItemModel ancestorListItem(WidgetModel widget) {
        for (int i = 0; i < 12 && widget != null; i++, widget = widget.getParent()) {
            if (widget instanceof ListItemModel) {
                return (ListItemModel) widget;
            }
        }
        throw new IllegalStateException("Native list-item ancestor missing");
    }

    private static WidgetModel required(WidgetModel root, int id) {
        WidgetModel result = findId(root, id);
        if (result == null) {
            throw new IllegalStateException(new StringBuffer("Missing stock template ").append(id).toString());
        }
        return result;
    }

    static WidgetModel findId(WidgetModel root, int id) {
        if (root.get_targetId() == id) {
            return root;
        }
        if (root instanceof ContainerModel) {
            WidgetModel[] children = ((ContainerModel) root).getChildren();
            for (int i = 0; children != null && i < children.length; i++) {
                WidgetModel result = findId(children[i], id);
                if (result != null) {
                    return result;
                }
            }
        }
        return null;
    }

    private static WidgetModel findListItem(WidgetModel root) {
        if (root instanceof ListItemModel) {
            return root;
        }
        if (root instanceof ContainerModel) {
            WidgetModel[] children = ((ContainerModel) root).getChildren();
            for (int i = 0; children != null && i < children.length; i++) {
                WidgetModel result = findListItem(children[i]);
                if (result != null) {
                    return result;
                }
            }
        }
        return null;
    }

    private static ButtonModel findButton(WidgetModel root) {
        if (root instanceof ButtonModel) {
            return (ButtonModel) root;
        }
        if (root instanceof ContainerModel) {
            WidgetModel[] children = ((ContainerModel) root).getChildren();
            for (int i = 0; children != null && i < children.length; i++) {
                ButtonModel result = findButton(children[i]);
                if (result != null) {
                    return result;
                }
            }
        }
        return null;
    }

    static WidgetModel find(WidgetModel root, String name) {
        if (name.equals(root.get_name())) {
            return root;
        }
        if (root instanceof ContainerModel) {
            WidgetModel[] children = ((ContainerModel) root).getChildren();
            for (int i = 0; children != null && i < children.length; i++) {
                WidgetModel result = find(children[i], name);
                if (result != null) {
                    return result;
                }
            }
        }
        return null;
    }

    /**
     * Deep copy of a factory widget subtree: same classes, every get_/is_ property copied through its set_ twin,
     * references inside the subtree remapped to the copies, a fresh UI object of the same class, a new targetId.
     */
    private WidgetModel cloneTree(WidgetModel source) throws Exception {
        copies.clear();
        collect(source);
        Enumeration keys = copies.keys();
        while (keys.hasMoreElements()) {
            WidgetModel from = (WidgetModel) keys.nextElement();
            WidgetModel to = (WidgetModel) copies.get(from);
            Method[] pairs = accessors(from.getClass());
            for (int i = 0; i < pairs.length; i += 2) {
                pairs[i + 1].invoke(to, new Object[] {remap(pairs[i].invoke(from, new Object[0]))});
            }
            to.set_name(from.get_name());
            to.set_targetId(nextId++);
            if (from.getUI() != null) {
                WidgetUI ui = (WidgetUI) from.getUI().getClass().newInstance();
                to.setUI(ui);
                ui.setWidget(to);
            }
            if (from instanceof ContainerModel) {
                ((ContainerModel) to).setChildren((WidgetModel[]) remap(((ContainerModel) from).getChildren()));
            }
            to.enablePropertyChanged();
        }
        return (WidgetModel) copies.get(source);
    }

    /** Per widget class (copies have the class of their source): getter, setter, getter, setter, ... Built once. */
    private static final Hashtable ACCESSORS = new Hashtable();

    private static Method[] accessors(Class type) throws Exception {
        Method[] cached = (Method[]) ACCESSORS.get(type);
        if (cached != null) {
            return cached;
        }
        Vector found = new Vector();
        Method[] methods = type.getMethods();
        for (int i = 0; i < methods.length; i++) {
            Method getter = methods[i];
            String name = getter.getName();
            int prefix = name.startsWith("get_") ? 4 : name.startsWith("is_") ? 3 : 0;
            if (prefix == 0 || getter.getParameterTypes().length != 0 || name.equals("is_activated")) {
                continue;
            }
            try {
                Method setter = type.getMethod(new StringBuffer("set_").append(name.substring(prefix)).toString(),
                        new Class[] {getter.getReturnType()});
                found.addElement(getter);
                found.addElement(setter);
            } catch (NoSuchMethodException ignored) {
                // read-only property
            }
        }
        Method[] pairs = new Method[found.size()];
        found.copyInto(pairs);
        ACCESSORS.put(type, pairs);
        return pairs;
    }

    private void collect(WidgetModel from) throws Exception {
        WidgetModel to = (WidgetModel) from.getClass().newInstance();
        to.disablePropertyChanged();
        copies.put(from, to);
        if (from instanceof ContainerModel) {
            WidgetModel[] children = ((ContainerModel) from).getChildren();
            for (int i = 0; children != null && i < children.length; i++) {
                collect(children[i]);
            }
        }
    }

    private Object remap(Object value) {
        if (value instanceof WidgetModel) {
            // A reference out of the copied subtree (for example a popup elsewhere in the view) becomes null.
            return copies.get(value);
        }
        if (value instanceof WidgetModel[]) {
            WidgetModel[] old = (WidgetModel[]) value;
            Object array = Array.newInstance(value.getClass().getComponentType(), old.length);
            for (int i = 0; i < old.length; i++) {
                Array.set(array, i, old[i] == null ? null : copies.get(old[i]));
            }
            return array;
        }
        return value;
    }
}
