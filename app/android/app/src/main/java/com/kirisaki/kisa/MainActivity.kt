package com.kirisaki.kisa

import android.annotation.SuppressLint
import android.content.Context
import android.content.SharedPreferences
import android.os.Bundle
import android.view.Menu
import android.view.MenuItem
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.EditText
import android.widget.Toast
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity

/**
 * Wrapper WebView KISA (Patch 3.3, S138 Cara 3).
 *
 * Aplikasi ini TIDAK memonitor HP — ia membuka dashboard server KISA yang
 * jalan di PC lewat Wi-Fi yang sama. Alamat server (mis. http://192.168.1.10:8000)
 * dimasukkan sekali, lalu disimpan. Menu "Ubah alamat server" untuk ganti PC.
 */
class MainActivity : AppCompatActivity() {

    private lateinit var webView: WebView
    private lateinit var prefs: SharedPreferences

    companion object {
        private const val PREFS = "kisa"
        private const val KEY_URL = "dashboard_url"
        private const val DEFAULT_HINT = "http://192.168.1.10:8000"
    }

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        prefs = getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        webView = WebView(this)
        webView.settings.javaScriptEnabled = true
        webView.settings.domStorageEnabled = true
        webView.settings.mixedContentMode = WebSettings.MIXED_CONTENT_ALWAYS_ALLOW
        webView.settings.loadsImagesAutomatically = true
        webView.webViewClient = WebViewClient()
        setContentView(webView)
        val url = prefs.getString(KEY_URL, null)
        if (url.isNullOrBlank()) askForAddress() else webView.loadUrl(url)
    }

    override fun onCreateOptionsMenu(menu: Menu): Boolean {
        menu.add(0, 1, 0, "Ubah alamat server")
        menu.add(0, 2, 0, "Muat ulang")
        return true
    }

    override fun onOptionsItemSelected(item: MenuItem): Boolean {
        return when (item.itemId) {
            1 -> { askForAddress(); true }
            2 -> { webView.reload(); true }
            else -> super.onOptionsItemSelected(item)
        }
    }

    private fun askForAddress() {
        val input = EditText(this)
        input.hint = DEFAULT_HINT
        input.setText(prefs.getString(KEY_URL, "") ?: "")
        AlertDialog.Builder(this)
            .setTitle("Alamat server KISA")
            .setMessage("Masukkan alamat dashboard di PC (satu Wi-Fi yang sama), contoh: http://192.168.1.10:8000")
            .setView(input)
            .setPositiveButton("Hubungkan") { _, _ ->
                val url = input.text.toString().trim()
                if (url.isBlank()) {
                    Toast.makeText(this, "Alamat masih kosong.", Toast.LENGTH_SHORT).show()
                    return@setPositiveButton
                }
                prefs.edit().putString(KEY_URL, url).apply()
                webView.loadUrl(url)
            }
            .setNegativeButton("Batal", null)
            .show()
    }

    @Deprecated("Dipakai untuk tombol kembali WebView.")
    override fun onBackPressed() {
        if (webView.canGoBack()) webView.goBack() else super.onBackPressed()
    }
}
