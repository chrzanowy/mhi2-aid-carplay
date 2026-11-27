/* pmcp (rg/lanes/wl.py, A248): route guidance of CarPlay over Wi-Fi (WL receiver, wlcpd). wlcpd writes the same RGM1/RGI1
 * mailbox as the wired reader (rgi-observer) to its own directory /ramdisk/pmcp-wl-rg. rg reads it only while a Wi-Fi
 * session owns the MOST map contract (bridge/contract, v=1 line files in /ramdisk/most-src):
 *   owner            "v=1 src=wireless pid=P gen=G ..."  and P alive (/proc/P exists on QNX)
 *   wireless.session "v=1 state=start gen=G ..."         with the same G
 * The cable takes the owner (src=wired) whenever it is connected, so the cable wins over Wi-Fi by the contract itself.
 * The files are read at most every PERIOD ms (shared by the HMI and the reader thread); anything missing, unreadable or
 * not exactly in that form means "not Wi-Fi" (the wired directory, as before A248).
 * Java 1.2 / CDC: no StringBuilder, no String.split, no generics or boxing.
 * SPDX-License-Identifier: GPL-3.0-or-later */
package com.cpmap.rgi;

import java.io.File;
import java.io.FileInputStream;

final class WlSource {
    static String ROOT="/ramdisk/pmcp-wl-rg";      // not final: the host tests point these at temporary directories
    static String SRC_DIR="/ramdisk/most-src";
    static String PROC="/proc";
    static final long PERIOD=500;
    static long checkedAt=-1;
    static volatile boolean active;
    static volatile long reads;

    private WlSource() {}

    /** Wi-Fi owns the map contract now (cached for PERIOD ms of System.currentTimeMillis()). */
    static boolean active() {
        long now=System.currentTimeMillis();
        if (checkedAt<0 || now<checkedAt || now-checkedAt>=PERIOD) {
            checkedAt=now;
            active=check();
        }
        return active;
    }

    /** Forget the cached answer (tests). */
    static void reset() { checkedAt=-1; }

    static boolean check() {
        try {
            reads++;
            String owner=line(path(SRC_DIR,"/owner"));
            String session=line(path(SRC_DIR,"/wireless.session"));
            if (owner==null || session==null) return false;
            if (!"1".equals(value(owner,"v")) || !"wireless".equals(value(owner,"src"))) return false;
            if (!"1".equals(value(session,"v")) || !"start".equals(value(session,"state"))) return false;
            String pid=value(owner,"pid"), gen=value(owner,"gen");
            if (!digits(pid) || !digits(gen) || !gen.equals(value(session,"gen"))) return false;
            if (Long.parseLong(pid)<=1) return false;
            return new File(path(PROC,path("/",pid))).exists();
        } catch (Throwable t) {
            return false;
        }
    }

    static String path(String a,String b) { return new StringBuffer(a).append(b).toString(); }

    static boolean digits(String s) {
        if (s==null || s.length()==0 || s.length()>10) return false;
        for (int i=0;i<s.length();i++) { char c=s.charAt(i); if (c<'0' || c>'9') return false; }
        return true;
    }

    /** The value of key in a "k=v k=v" line (exact key, space separated), or null. */
    static String value(String line,String key) {
        int at=0, n=line.length();
        while (at<n) {
            int end=line.indexOf(' ',at);
            if (end<0) end=n;
            int eq=line.indexOf('=',at);
            if (eq>at && eq<end && eq-at==key.length() && line.regionMatches(at,key,0,key.length()))
                return line.substring(eq+1,end);
            at=end+1;
        }
        return null;
    }

    /** First line of a contract file (at most 255 bytes, printable ASCII), or null. */
    static String line(String name) {
        FileInputStream in=null;
        byte[] b=new byte[256];
        int n=0;
        try {
            in=new FileInputStream(name);
            int r;
            while (n<b.length && (r=in.read(b,n,b.length-n))>0) n+=r;
        } catch (Throwable t) {
            n=-1;
        }
        try { if (in!=null) in.close(); } catch (Throwable t) {}
        if (n<=0 || n>=b.length) return null;
        int end=0;
        while (end<n && b[end]!='\n') {
            if (b[end]<0x20 || b[end]>0x7e) return null;
            end++;
        }
        char[] c=new char[end];
        for (int i=0;i<end;i++) c[i]=(char)b[i];
        return new String(c);
    }
}
