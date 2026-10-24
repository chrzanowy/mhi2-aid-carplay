/* SPDX-License-Identifier: GPL-3.0-or-later */
package com.pmcp.zoom;

import java.net.DatagramPacket;
import java.net.DatagramSocket;
import java.net.InetAddress;

/**
 * Package F: steering-wheel up/down -> CarPlay cluster map zoom.
 * Called at the start of the stock DSIKeyPanelDispatcher.updateKey2 (patcher/PatchExtras.java), only for keyboard 4
 * (the patcher also checks that inline). The key is not consumed: the stock handling continues unchanged.
 *
 * A press of MFW up/down (keys 38/39, state 1) sends "zoom-in"/"zoom-out" over UDP 127.0.0.1:7032 to core.so
 * (map_control_command_worker -> changeMapZoomLevel); repeats of a held key are ignored until it is released.
 * Protocol and key codes as in omonob/mathsls Mhi2ClusterControlBridge (GPL-3.0). Unlike that bridge there is no
 * long-press action: theirs sends map-previous/map-next after 2.5 s, which core.so turns into a cluster app switch,
 * and holding an arrow is also how cluster lists are scrolled (review 2, finding 3; user decision 2026-10-21).
 * The UDP send runs on one daemon thread with one reused socket, never on the key thread. Java 1.2 clean, every error
 * swallowed: the keys must keep working.
 */
public final class ZoomHook {
    static final int KEYBOARD_MFW = 4;
    static final int KEY_UP = 38;
    static final int KEY_DOWN = 39;
    static final int STATE_RELEASED = 0;
    static final int STATE_PRESSED = 1;
    static final int PORT = 7032;
    static final String ZOOM_IN = "zoom-in";
    static final String ZOOM_OUT = "zoom-out";

    private static final Object LOCK = new Object();
    private static final String[] QUEUE = new String[8];
    private static int head;
    private static int count;
    private static int held = -1;
    private static boolean started;

    private ZoomHook() {
    }

    public static void onKey2(int keyboard, int key, int state, int param3, int valid) {
        try {
            if (keyboard != KEYBOARD_MFW || (key != KEY_UP && key != KEY_DOWN)) {
                return;
            }
            synchronized (LOCK) {
                String command = command(key, state);
                if (command == null) {
                    return;
                }
                if (!started) {
                    Thread t = new Thread(new Runnable() {
                        public void run() {
                            sendLoop();
                        }
                    }, "pmcp-zoom");
                    t.setDaemon(true);
                    t.start();
                    started = true;
                }
                if (count == QUEUE.length) {   // full: drop the oldest
                    head = (head + 1) % QUEUE.length;
                    count--;
                }
                QUEUE[(head + count) % QUEUE.length] = command;
                count++;
                LOCK.notifyAll();
            }
        } catch (Throwable t) {
            // stock key handling continues
        }
    }

    /** Caller holds LOCK. */
    static String command(int key, int state) {
        if (state == STATE_PRESSED) {
            if (held == key) {
                return null;
            }
            held = key;
            return key == KEY_UP ? ZOOM_IN : ZOOM_OUT;
        }
        if (state == STATE_RELEASED && held == key) {
            held = -1;
        }
        return null;
    }

    static void sendLoop() {
        DatagramSocket socket = null;
        InetAddress loopback = null;
        for (;;) {
            String command;
            try {
                synchronized (LOCK) {
                    while (count == 0) {
                        LOCK.wait();
                    }
                    command = QUEUE[head];
                    QUEUE[head] = null;
                    head = (head + 1) % QUEUE.length;
                    count--;
                }
            } catch (Throwable t) {
                continue;
            }
            try {
                byte[] bytes = command.getBytes("US-ASCII");
                if (socket == null) {
                    socket = new DatagramSocket();
                }
                if (loopback == null) {
                    loopback = InetAddress.getByName("127.0.0.1");
                }
                socket.send(new DatagramPacket(bytes, bytes.length, loopback, PORT));
            } catch (Throwable t) {
                if (socket != null) {
                    socket.close();
                }
                socket = null;
                loopback = null;
            }
        }
    }
}
