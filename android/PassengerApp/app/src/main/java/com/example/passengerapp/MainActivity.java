package com.example.passengerapp;

import android.os.Bundle;
import android.widget.TextView;
import androidx.activity.EdgeToEdge;
import androidx.appcompat.app.AppCompatActivity;
import androidx.core.graphics.Insets;
import androidx.core.view.ViewCompat;
import androidx.core.view.WindowInsetsCompat;
import android.view.View;
import android.widget.Button;
import android.widget.Toast;
import com.android.volley.Request;
import com.android.volley.RequestQueue;
import com.android.volley.toolbox.JsonObjectRequest;
import com.android.volley.toolbox.Volley;
import org.json.JSONObject;
import org.json.JSONException;
import com.android.volley.toolbox.StringRequest;
import android.location.Location;
import com.google.android.gms.location.FusedLocationProviderClient;
import com.google.android.gms.location.LocationCallback;
import com.google.android.gms.location.LocationRequest;
import com.google.android.gms.location.LocationResult;
import com.google.android.gms.location.LocationServices;
import android.content.pm.PackageManager;
import androidx.core.app.ActivityCompat;
import androidx.annotation.NonNull;
import com.google.android.gms.location.Priority;
import java.util.List;
import java.util.ArrayList;





public class MainActivity extends AppCompatActivity
{

    Button btnStart, btnStop, btnSOS;
    String currentTripId = null;
    private Location lastLocation = null;
    private TextView txtSpeed;
    private List<Float> speedBuffer = new ArrayList<>();
    private int bufferSize = 5;
    FusedLocationProviderClient locationClient;
    LocationCallback locationCallback;
    @Override
    public void onRequestPermissionsResult(
            int requestCode,
            @NonNull String[] permissions,
            @NonNull int[] grantResults
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);

        if (requestCode == 1001) {
            if (grantResults.length > 0
                    && grantResults[0] == PackageManager.PERMISSION_GRANTED) {

                startLocationUpdates();

            } else {
                Toast.makeText(this,
                        "Location permission denied",
                        Toast.LENGTH_LONG).show();
            }
        }
    }
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        EdgeToEdge.enable(this);
        setContentView(R.layout.activity_main);
        txtSpeed = findViewById(R.id.txtSpeed);
        locationClient = LocationServices.getFusedLocationProviderClient(this);
        btnStart = findViewById(R.id.btnStart);
        btnStop  = findViewById(R.id.btnStop);
        btnSOS   = findViewById(R.id.btnSOS);
        if (ActivityCompat.checkSelfPermission(
                this, android.Manifest.permission.ACCESS_FINE_LOCATION)
                != PackageManager.PERMISSION_GRANTED) {

            ActivityCompat.requestPermissions(
                    this,
                    new String[]{android.Manifest.permission.ACCESS_FINE_LOCATION},
                    1001
            );
        }
        btnStart.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {

                String url = "http://172.29.136.120:5000/trips";

                RequestQueue queue = Volley.newRequestQueue(MainActivity.this);

                JSONObject body = new JSONObject();
                try {
                    body.put("driver_id", "driver_001");
                } catch (JSONException e) {
                    e.printStackTrace();
                }

                JsonObjectRequest request = new JsonObjectRequest(
                        Request.Method.POST,
                        url,
                        body,
                        response -> {
                            try {
                                currentTripId = response.getString("trip_id");
                                Toast.makeText(MainActivity.this,
                                        "Trip started",
                                        Toast.LENGTH_SHORT).show();
                            } catch (JSONException e) {
                                e.printStackTrace();
                            }
                        },
                        error -> {
                            String message = "Unknown error";

                            if (error.networkResponse != null) {
                                message = "Error Code: " + error.networkResponse.statusCode;
                            } else if (error.getMessage() != null) {
                                message = error.getMessage();
                            }

                            Toast.makeText(MainActivity.this,
                                    message,
                                    Toast.LENGTH_LONG).show();
                        }
                );

                queue.add(request);
            }
        });
        btnStop.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {

                // 1. Check if there is an active trip
                if (currentTripId == null) {
                    Toast.makeText(MainActivity.this,
                            "No active trip",
                            Toast.LENGTH_SHORT).show();
                    return;
                }

                // 2. Prepare URL
                String url = "http://172.29.136.120:5000/trips/" + currentTripId + "/end";

                RequestQueue queue = Volley.newRequestQueue(MainActivity.this);

                // 3. Create PUT request (no body needed)
                StringRequest request = new StringRequest(
                        Request.Method.PUT,
                        url,
                        response -> {
                            // 4. Clear active trip
                            currentTripId = null;
                            Toast.makeText(MainActivity.this,
                                    "Trip ended",
                                    Toast.LENGTH_SHORT).show();
                        },
                        error -> {
                            Toast.makeText(MainActivity.this,
                                    "Failed to end trip",
                                    Toast.LENGTH_SHORT).show();
                        }
                );

                // 5. Send request
                queue.add(request);
            }
        });
        btnSOS.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {

                if (currentTripId == null) {
                    Toast.makeText(MainActivity.this,
                            "SOS pressed (no active trip)",
                            Toast.LENGTH_SHORT).show();
                } else {
                    Toast.makeText(MainActivity.this,
                            "SOS triggered during trip",
                            Toast.LENGTH_SHORT).show();
                }

            }
        });
        locationCallback = new LocationCallback() {
            @Override
            public void onLocationResult(LocationResult locationResult) {
                if (locationResult == null) return;
                if (currentTripId == null) {
                    return; // trip not active → do nothing
                }

                for (Location location : locationResult.getLocations()) {

                    // Ignore bad accuracy
                    if (location.hasAccuracy() && location.getAccuracy() > 20) {
                        continue;
                    }

                    // --- ALWAYS UPDATE SPEED UI ---
                    float speedMps = location.getSpeed();
                    float speedKmph = speedMps * 3.6f;

                    speedBuffer.add(speedKmph);
                    if (speedBuffer.size() > bufferSize) {
                        speedBuffer.remove(0);
                    }

                    float sum = 0;
                    for (float s : speedBuffer) {
                        sum += s;
                    }
                    float smoothedSpeed = sum / speedBuffer.size();

                    txtSpeed.setText(String.format("Speed: %.2f km/h", smoothedSpeed));

                    if (smoothedSpeed > 80) {
                        txtSpeed.setTextColor(getResources().getColor(android.R.color.holo_red_dark));
                    } else {
                        txtSpeed.setTextColor(getResources().getColor(android.R.color.white));
                    }

                    // --- ONLY SEND TO BACKEND IF MOVED > 5m ---
                    if (lastLocation != null) {
                        float distance = lastLocation.distanceTo(location);
                        if (distance < 5) {
                            continue;  // Skip backend update, but UI already updated
                        }
                    }

                    lastLocation = location;

                    sendLocationToBackend(
                            location.getLatitude(),
                            location.getLongitude(),
                            location.getTime(),
                            smoothedSpeed
                    );
                }

            }
        };
        ViewCompat.setOnApplyWindowInsetsListener(findViewById(R.id.main), (v, insets) -> {
            Insets systemBars = insets.getInsets(WindowInsetsCompat.Type.systemBars());
            v.setPadding(systemBars.left, systemBars.top, systemBars.right, systemBars.bottom);
            return insets;
        });
        LocationRequest locationRequest = LocationRequest.create();
        locationRequest.setInterval(5000);        // 5 seconds
        locationRequest.setFastestInterval(3000);
        locationRequest.setPriority(LocationRequest.PRIORITY_HIGH_ACCURACY);

        if (ActivityCompat.checkSelfPermission(
                this,
                android.Manifest.permission.ACCESS_FINE_LOCATION
        ) == PackageManager.PERMISSION_GRANTED) {

            startLocationUpdates();
        }
    }
    private void startLocationUpdates() {

        LocationRequest locationRequest =
                new LocationRequest.Builder(5000)
                        .setMinUpdateIntervalMillis(3000)
                        .setMinUpdateDistanceMeters(5)
                        .setPriority(Priority.PRIORITY_HIGH_ACCURACY)
                        .build();

        if (ActivityCompat.checkSelfPermission(
                this,
                android.Manifest.permission.ACCESS_FINE_LOCATION
        ) == PackageManager.PERMISSION_GRANTED) {

            locationClient.requestLocationUpdates(
                    locationRequest,
                    locationCallback,
                    getMainLooper()
            );

            Toast.makeText(this,
                    "GPS updates started",
                    Toast.LENGTH_SHORT).show();
        }
    }
    private void sendLocationToBackend(double lat, double lon, long time, float speed) {

        String url = "http://172.29.136.120:5000/trips/" + currentTripId + "/location";

        RequestQueue queue = Volley.newRequestQueue(this);

        JSONObject body = new JSONObject();
        try {
            body.put("latitude", lat);
            body.put("longitude", lon);
            body.put("speed", speed);
            body.put("timestamp", time);
        } catch (JSONException e) {
            e.printStackTrace();
        }

        JsonObjectRequest request = new JsonObjectRequest(
                Request.Method.POST,
                url,
                body,
                response -> {
                    // success → no UI action needed
                },
                error -> {
                    // optional: log error
                }
        );

        queue.add(request);
    }
}