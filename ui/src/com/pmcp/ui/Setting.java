/* SPDX-License-Identifier: GPL-3.0-or-later */
package com.pmcp.ui;

/**
 * One row of the settings page: a name, a short list of choices, the saved choice and a store. The page owns no
 * values; it asks the row each time it draws. New rows (map layout, fps, IDR) are new subclasses.
 *
 * Runs on the HMI thread on the unit (J9, CDC 1.1 class library): no StringBuilder, no autoboxing, no class literals.
 */
abstract class Setting {
    /** Row name on the page. */
    abstract String label();

    /** Number of choices, 1..SettingsPage.MAX_CHOICES. */
    abstract int count();

    /** Text of choice i (popup and row value). */
    abstract String choice(int i);

    /** The saved choice, or -1 when the stored value is missing or invalid. */
    abstract int current();

    /** Text for the row value when current() is -1. */
    abstract String invalidText();

    /** null when choice i can be selected now, otherwise a short reason (one line on the page). */
    abstract String blocked(int i);

    /** Saves choice i. Returns the line shown under the row; throws with a short reason when nothing was saved. */
    abstract String select(int i) throws Exception;

    /** Line shown under the rows when the page opens; the first row with a non-null hint wins. */
    abstract String hint();

    /** Row value text: the saved choice, or invalidText() when there is none. */
    String valueText() {
        int current = current();
        return current < 0 || current >= count() ? invalidText() : choice(current);
    }
}
