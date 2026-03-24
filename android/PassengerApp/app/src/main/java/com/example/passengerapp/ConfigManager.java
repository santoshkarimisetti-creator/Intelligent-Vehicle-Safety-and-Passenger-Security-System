package com.example.passengerapp;

import android.content.Context;
import android.content.SharedPreferences;
import android.net.nsd.NsdManager;
import android.net.nsd.NsdServiceInfo;
import android.net.wifi.WifiManager;
import android.util.Log;
import java.net.Inet4Address;
import java.net.InetAddress;
import java.net.NetworkInterface;
import java.net.URL;
import java.util.Enumeration;

public class ConfigManager {
    private static final String TAG = "ConfigManager";
    private static final String PREFS_NAME = "ivs_config";
    private static final String KEY_BACKEND_URL = "backend_url";
    private static final String KEY_WIFI_SSID = "wifi_ssid";
    private static final String DEFAULT_BACKEND_URL = "http://192.168.55.101:5000";
    private static final String SERVICE_TYPE = "_http._tcp.";

    private final SharedPreferences prefs;
    private final NsdManager nsdManager;
    private final WifiManager wifiManager;
    private NsdManager.DiscoveryListener discoveryListener;
    private WifiManager.MulticastLock multicastLock;
    private boolean discoveryInProgress = false;

    public ConfigManager(Context context) {
        this.prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE);
        this.nsdManager = (NsdManager) context.getSystemService(Context.NSD_SERVICE);
        this.wifiManager = (WifiManager) context.getApplicationContext().getSystemService(Context.WIFI_SERVICE);
    }

    public String getBackendUrl() {
        String cachedUrl = prefs.getString(KEY_BACKEND_URL, null);
        if (cachedUrl != null && !cachedUrl.isEmpty()) {
            if (isCachedUrlUsableOnCurrentNetwork(cachedUrl)) {
                Log.d(TAG, "Using cached URL: " + cachedUrl);
                return cachedUrl;
            }
            Log.d(TAG, "Cached URL appears stale for current network. Clearing cache.");
            clearCache();
            refreshBackendUrlAsync();
        }

        Log.d(TAG, "Using default URL: " + DEFAULT_BACKEND_URL);
        return DEFAULT_BACKEND_URL;
    }

    public void refreshBackendUrlAsync() {
        if (nsdManager == null) {
            Log.e(TAG, "NsdManager not available");
            return;
        }

        if (discoveryInProgress) {
            return;
        }

        discoveryInProgress = true;
        acquireMulticastLock();

        discoveryListener = new NsdManager.DiscoveryListener() {
            @Override
            public void onDiscoveryStarted(String serviceType) {
                Log.d(TAG, "Discovery started: " + serviceType);
            }

            @Override
            public void onServiceFound(NsdServiceInfo serviceInfo) {
                Log.d(TAG, "Service found: " + serviceInfo.getServiceName());
                boolean looksLikeIvs =
                        serviceInfo.getServiceName().toLowerCase().contains("ivs") ||
                        serviceInfo.getServiceType().toLowerCase().contains("ivs");

                if (!looksLikeIvs) {
                    return;
                }

                nsdManager.resolveService(serviceInfo, new NsdManager.ResolveListener() {
                    @Override
                    public void onResolveFailed(NsdServiceInfo serviceInfo, int errorCode) {
                        Log.e(TAG, "Resolve failed: " + errorCode);
                    }

                    @Override
                    public void onServiceResolved(NsdServiceInfo serviceInfo) {
                        if (serviceInfo.getHost() == null) {
                            return;
                        }
                        String host = serviceInfo.getHost().getHostAddress();
                        int port = serviceInfo.getPort();
                        String discoveredUrl = "http://" + host + ":" + port;
                        cacheBackendUrl(discoveredUrl);
                        Log.d(TAG, "Service resolved and cached: " + discoveredUrl);
                        stopDiscovery();
                    }
                });
            }

            @Override
            public void onServiceLost(NsdServiceInfo serviceInfo) {
                Log.d(TAG, "Service lost: " + serviceInfo.getServiceName());
            }

            @Override
            public void onDiscoveryStopped(String serviceType) {
                discoveryInProgress = false;
                Log.d(TAG, "Discovery stopped: " + serviceType);
            }

            @Override
            public void onStartDiscoveryFailed(String serviceType, int errorCode) {
                Log.e(TAG, "Start discovery failed: " + errorCode);
                stopDiscovery();
            }

            @Override
            public void onStopDiscoveryFailed(String serviceType, int errorCode) {
                Log.e(TAG, "Stop discovery failed: " + errorCode);
                discoveryInProgress = false;
            }
        };

        try {
            nsdManager.discoverServices(SERVICE_TYPE, NsdManager.PROTOCOL_DNS_SD, discoveryListener);
        } catch (Exception e) {
            Log.e(TAG, "NSD discovery failed", e);
            discoveryInProgress = false;
        }
    }

    private void stopDiscovery() {
        if (nsdManager == null || discoveryListener == null) {
            discoveryInProgress = false;
            releaseMulticastLock();
            return;
        }

        try {
            nsdManager.stopServiceDiscovery(discoveryListener);
        } catch (Exception e) {
            Log.e(TAG, "Error stopping discovery", e);
        } finally {
            discoveryInProgress = false;
            discoveryListener = null;
            releaseMulticastLock();
        }
    }

    private void acquireMulticastLock() {
        try {
            if (wifiManager == null) {
                return;
            }
            if (multicastLock == null) {
                multicastLock = wifiManager.createMulticastLock("ivs-nsd-lock");
                multicastLock.setReferenceCounted(false);
            }
            if (!multicastLock.isHeld()) {
                multicastLock.acquire();
            }
        } catch (Exception e) {
            Log.e(TAG, "Failed to acquire multicast lock", e);
        }
    }

    private void releaseMulticastLock() {
        try {
            if (multicastLock != null && multicastLock.isHeld()) {
                multicastLock.release();
            }
        } catch (Exception e) {
            Log.e(TAG, "Failed to release multicast lock", e);
        }
    }

    private void cacheBackendUrl(String url) {
        String ssid = getCurrentWiFiSSID();
        prefs.edit()
            .putString(KEY_BACKEND_URL, url)
            .putString(KEY_WIFI_SSID, ssid)
            .apply();
        Log.d(TAG, "Cached URL: " + url + " on WiFi: " + ssid);
    }
    
    private String getCurrentWiFiSSID() {
        try {
            if (wifiManager == null) {
                return null;
            }
            android.net.wifi.WifiInfo wifiInfo = wifiManager.getConnectionInfo();
            if (wifiInfo != null && wifiInfo.getNetworkId() != -1) {
                String ssid = wifiInfo.getSSID();
                if (ssid != null) {
                    // Remove quotes if present
                    ssid = ssid.replace("\"", "");
                }
                return ssid;
            }
        } catch (Exception e) {
            Log.e(TAG, "Failed to get WiFi SSID", e);
        }
        return null;
    }

    private boolean isCachedUrlUsableOnCurrentNetwork(String cachedUrl) {
        try {
            // Check if still on same WiFi network
            String currentSSID = getCurrentWiFiSSID();
            String cachedSSID = prefs.getString(KEY_WIFI_SSID, null);
            
            if (currentSSID != null && cachedSSID != null && !currentSSID.equals(cachedSSID)) {
                Log.d(TAG, "WiFi changed from '" + cachedSSID + "' to '" + currentSSID + "'. Invalidating cache.");
                return false;
            }
            
            // Check subnet match
            String cachedHost = new URL(cachedUrl).getHost();
            if (cachedHost == null || cachedHost.isEmpty() || !cachedHost.matches("\\d+\\.\\d+\\.\\d+\\.\\d+")) {
                return true;  // Not an IP, assume it's mDNS hostname - usable
            }

            String localIp = getLocalIpv4Address();
            if (localIp == null || !localIp.matches("\\d+\\.\\d+\\.\\d+\\.\\d+")) {
                return true;  // Can't determine local IP, assume cached URL is OK
            }

            String[] cachedParts = cachedHost.split("\\.");
            String[] localParts = localIp.split("\\.");
            if (cachedParts.length < 3 || localParts.length < 3) {
                return true;
            }

            boolean sameSubnet = cachedParts[0].equals(localParts[0])
                    && cachedParts[1].equals(localParts[1])
                    && cachedParts[2].equals(localParts[2]);
            
            if (!sameSubnet) {
                Log.d(TAG, "Cached URL " + cachedHost + " not on same subnet as " + localIp);
            }
            
            return sameSubnet;
        } catch (Exception e) {
            Log.e(TAG, "Failed to validate cached URL. Using it as fallback.", e);
            return true;
        }
    }

    private String getLocalIpv4Address() {
        try {
            Enumeration<NetworkInterface> interfaces = NetworkInterface.getNetworkInterfaces();
            while (interfaces != null && interfaces.hasMoreElements()) {
                NetworkInterface networkInterface = interfaces.nextElement();
                Enumeration<InetAddress> addresses = networkInterface.getInetAddresses();
                while (addresses.hasMoreElements()) {
                    InetAddress address = addresses.nextElement();
                    if (!address.isLoopbackAddress() && address instanceof Inet4Address && address.isSiteLocalAddress()) {
                        return address.getHostAddress();
                    }
                }
            }
        } catch (Exception e) {
            Log.e(TAG, "Unable to resolve local IP", e);
        }
        return null;
    }

    public String buildUrl(String endpoint) {
        return getBackendUrl() + endpoint;
    }

    public void clearCache() {
        prefs.edit().remove(KEY_BACKEND_URL).apply();
    }
}
