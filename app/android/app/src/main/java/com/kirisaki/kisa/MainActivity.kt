package com.kirisaki.kisa

import android.Manifest
import android.annotation.SuppressLint
import android.app.Dialog
import android.content.Context
import android.content.Intent
import android.content.SharedPreferences
import android.content.pm.ActivityInfo
import android.content.pm.PackageManager
import android.content.res.Configuration
import android.graphics.Bitmap
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.ColorDrawable
import android.graphics.drawable.GradientDrawable
import android.net.Uri
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.text.InputType
import android.view.Gravity
import android.view.Menu
import android.view.MenuItem
import android.view.View
import android.view.ViewGroup
import android.webkit.JavascriptInterface
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Button
import android.widget.EditText
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.TextView
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.core.graphics.drawable.DrawableCompat

/**
 * Wrapper WebView KISA (Patch 3.7, S142 Cara 1).
 *
 * Aplikasi ini TIDAK memonitor HP — ia membuka dashboard server KISA yang
 * jalan di PC lewat Wi-Fi yang sama. Alamat server (mis. http://192.168.1.10:8000)
 * dimasukkan sekali, lalu disimpan. Menu "Ubah alamat server" untuk ganti PC.
 * Alamat juga bisa diisi dengan scan QR code dashboard (tombol "Scan QR").
 *
 * Patch 3.4: WebChromeClient (pemilih file + fullscreen) dan bridge JS KisaApp.setOrientation.
 * Patch 3.7: dialog alamat kustom S142 Cara 1 (kartu tengah, programatik, token
 * Nocturne mengikuti night mode sistem) + overlay loading / error dengan timeout
 * 15 detik saat dashboard gagal dimuat.
 */
class MainActivity : AppCompatActivity() {

    private lateinit var webView: WebView
    private lateinit var prefs: SharedPreferences
    private lateinit var rootLayout: FrameLayout
    private lateinit var loadingOverlay: LinearLayout
    private lateinit var errorOverlay: LinearLayout
    private var addressDialog: Dialog? = null

    // State siklus load dashboard (Patch 3.7): onPageFinished yang datang dari
    // load yang gagal tidak boleh menyembunyikan overlay error.
    private var loadInProgress = false
    private var loadFailed = false
    private var loadTimeoutFired = false
    private val loadHandler = Handler(Looper.getMainLooper())
    private val loadTimeoutRunnable = Runnable {
        if (loadInProgress && !loadFailed) {
            loadTimeoutFired = true
            loadInProgress = false
            hideLoadingOverlay()
            showErrorOverlay()
        }
    }

    companion object {
        private const val PREFS = "kisa"
        private const val KEY_URL = "dashboard_url"
        private const val DEFAULT_HINT = "http://192.168.1.10:8000"
        private const val LOAD_TIMEOUT_MS = 15_000L
    }

    private val permissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { granted ->
        if (granted) {
            launchScanner()
        } else {
            Toast.makeText(this, "Izin kamera diperlukan untuk scan QR.", Toast.LENGTH_SHORT).show()
        }
    }

    private val scanLauncher = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) { result ->
        if (result.resultCode == RESULT_OK) {
            val url = result.data?.getStringExtra(ScanActivity.EXTRA_URL)?.trim()
            if (!url.isNullOrBlank() &&
                (url.startsWith("http://") || url.startsWith("https://"))
            ) {
                prefs.edit().putString(KEY_URL, url).apply()
                loadDashboard(url)
            } else {
                Toast.makeText(this, "QR tidak berisi alamat dashboard.", Toast.LENGTH_SHORT).show()
                askForAddress()
            }
        }
    }

    private var fileChooserCallback: ValueCallback<Array<Uri>>? = null
    private var customView: View? = null
    private var customViewCallback: WebChromeClient.CustomViewCallback? = null
    private var fullscreenContainer: FrameLayout? = null

    private val fileChooserLauncher = registerForActivityResult(
        ActivityResultContracts.GetContent()
    ) { uri: Uri? ->
        val callback = fileChooserCallback
        fileChooserCallback = null
        if (uri != null) {
            callback?.onReceiveValue(arrayOf(uri))
        } else {
            callback?.onReceiveValue(null)
        }
    }

    // ------------------------------------------------------------------
    // Token warna Nocturne (sama seperti mockup S142), mengikuti night
    // mode sistem. Activity dibuat ulang saat tema sistem berubah, jadi
    // warna yang dihitung di onCreate selalu sesuai tema yang aktif.
    // ------------------------------------------------------------------

    private data class ThemeColors(
        val night: Boolean,
        val page: Int,
        val card: Int,
        val text: Int,
        val secondary: Int
    )

    private fun currentTheme(): ThemeColors {
        val night = (resources.configuration.uiMode and Configuration.UI_MODE_NIGHT_MASK) ==
            Configuration.UI_MODE_NIGHT_YES
        return if (night) {
            ThemeColors(
                night = true,
                page = 0xFF060606.toInt(),
                card = 0xFF0E0E0E.toInt(),
                text = 0xFFFAFAFA.toInt(),
                secondary = 0xFF8F8F8F.toInt()
            )
        } else {
            ThemeColors(
                night = false,
                page = 0xFFFFFFFF.toInt(),
                card = 0xFFFFFFFF.toInt(),
                text = 0xFF0A0A0A.toInt(),
                secondary = 0xFF636363.toInt()
            )
        }
    }

    private fun dp(value: Int): Int = (value * resources.displayMetrics.density).toInt()

    private fun cardBackground(t: ThemeColors): GradientDrawable {
        return GradientDrawable().apply {
            shape = GradientDrawable.RECTANGLE
            cornerRadius = dp(12).toFloat()
            setColor(t.card)
            setStroke(dp(1), if (t.night) 0x1FFFFFFF.toInt() else 0x1F000000.toInt())
        }
    }

    private fun primaryButton(t: ThemeColors, text: String): Button {
        return Button(this).apply {
            this.text = text
            setAllCaps(false)
            textSize = 14f
            setTypeface(typeface, Typeface.BOLD)
            setTextColor(Color.WHITE)
            background = GradientDrawable().apply {
                shape = GradientDrawable.RECTANGLE
                cornerRadius = dp(12).toFloat()
                setColor(0xFF3B82F6.toInt())
            }
            backgroundTintList = null
            setPadding(dp(12), dp(11), dp(12), dp(11))
        }
    }

    private fun secondaryButton(t: ThemeColors, text: String, withIcon: Boolean = false): Button {
        return Button(this).apply {
            this.text = text
            setAllCaps(false)
            textSize = 14f
            setTypeface(typeface, Typeface.BOLD)
            setTextColor(t.text)
            background = GradientDrawable().apply {
                shape = GradientDrawable.RECTANGLE
                cornerRadius = dp(10).toFloat()
                setColor(Color.TRANSPARENT)
                setStroke(dp(1), if (t.night) 0x38FFFFFF.toInt() else 0x38000000.toInt())
            }
            backgroundTintList = null
            setPadding(dp(12), dp(11), dp(12), dp(11))
            if (withIcon) {
                // Ikon framework yang pasti ada (bukan drawable aplikasi).
                val icon = ContextCompat.getDrawable(
                    this@MainActivity, android.R.drawable.ic_menu_camera
                )?.mutate()
                if (icon != null) {
                    DrawableCompat.setTint(icon, t.text)
                    setCompoundDrawablesWithIntrinsicBounds(icon, null, null, null)
                    compoundDrawablePadding = dp(7)
                }
            }
        }
    }

    private fun textButton(t: ThemeColors, text: String): Button {
        return Button(this).apply {
            this.text = text
            setAllCaps(false)
            textSize = 13f
            setTextColor(t.secondary)
            setBackgroundColor(Color.TRANSPARENT)
            backgroundTintList = null
            setPadding(dp(8), dp(4), dp(8), dp(4))
        }
    }

    private fun fullWidthParams(bottomMarginDp: Int = 8): LinearLayout.LayoutParams {
        return LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT,
            LinearLayout.LayoutParams.WRAP_CONTENT
        ).apply { bottomMargin = dp(bottomMarginDp) }
    }

    // ------------------------------------------------------------------
    // Overlay loading / error (Patch 3.7, Tugas 2).
    // ------------------------------------------------------------------

    private fun buildLoadingOverlay(t: ThemeColors): LinearLayout {
        return LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER
            setBackgroundColor(t.page)
            setPadding(dp(24), dp(24), dp(24), dp(24))
            visibility = View.GONE
            val spinner = ProgressBar(this@MainActivity)
            addView(
                spinner,
                LinearLayout.LayoutParams(
                    LinearLayout.LayoutParams.WRAP_CONTENT,
                    LinearLayout.LayoutParams.WRAP_CONTENT
                ).apply { gravity = Gravity.CENTER_HORIZONTAL }
            )
            val label = TextView(this@MainActivity).apply {
                text = "Menghubungkan ke PC…"
                textSize = 14f
                setTextColor(t.text)
                gravity = Gravity.CENTER
                setPadding(0, dp(16), 0, 0)
            }
            addView(
                label,
                LinearLayout.LayoutParams(
                    LinearLayout.LayoutParams.WRAP_CONTENT,
                    LinearLayout.LayoutParams.WRAP_CONTENT
                ).apply { gravity = Gravity.CENTER_HORIZONTAL }
            )
        }
    }

    private fun buildErrorOverlay(t: ThemeColors): LinearLayout {
        return LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER
            setBackgroundColor(t.page)
            setPadding(dp(24), dp(24), dp(24), dp(24))
            visibility = View.GONE
            val title = TextView(this@MainActivity).apply {
                text = "Tidak dapat terhubung ke PC"
                textSize = 16f
                setTypeface(typeface, Typeface.BOLD)
                setTextColor(t.text)
                gravity = Gravity.CENTER
            }
            addView(
                title,
                LinearLayout.LayoutParams(
                    LinearLayout.LayoutParams.MATCH_PARENT,
                    LinearLayout.LayoutParams.WRAP_CONTENT
                ).apply { bottomMargin = dp(4) }
            )
            val sub = TextView(this@MainActivity).apply {
                text = "Periksa server PC sudah jalan dan HP satu Wi-Fi yang sama."
                textSize = 12f
                setTextColor(t.secondary)
                gravity = Gravity.CENTER
            }
            addView(
                sub,
                LinearLayout.LayoutParams(
                    LinearLayout.LayoutParams.MATCH_PARENT,
                    LinearLayout.LayoutParams.WRAP_CONTENT
                ).apply { bottomMargin = dp(16) }
            )
            val retry = primaryButton(t, "Coba lagi")
            retry.setOnClickListener { retryLoad() }
            addView(retry, fullWidthParams(8))
            val change = secondaryButton(t, "Ubah alamat server")
            change.setOnClickListener { askForAddress() }
            addView(change, fullWidthParams(8))
            val scan = secondaryButton(t, "Scan QR", withIcon = true)
            scan.setOnClickListener { requestCameraAndScan() }
            addView(scan, fullWidthParams(0))
        }
    }

    private fun showLoadingOverlay() {
        errorOverlay.visibility = View.GONE
        loadingOverlay.visibility = View.VISIBLE
    }

    private fun hideLoadingOverlay() {
        loadingOverlay.visibility = View.GONE
    }

    private fun showErrorOverlay() {
        // Tanpa URL tersimpan tidak ada load yang bisa gagal — jangan tampilkan error.
        if (prefs.getString(KEY_URL, null).isNullOrBlank()) return
        loadingOverlay.visibility = View.GONE
        errorOverlay.visibility = View.VISIBLE
    }

    private fun hideErrorOverlay() {
        errorOverlay.visibility = View.GONE
    }

    private fun markLoadFailed() {
        loadFailed = true
        loadInProgress = false
        loadHandler.removeCallbacks(loadTimeoutRunnable)
        hideLoadingOverlay()
        showErrorOverlay()
    }

    /**
     * Satu-satunya jalur memuat dashboard: reset state, tampilkan loading,
     * pasang timeout 15 detik (Handler, tanpa blok UI thread). onPageStarted
     * memasang ulang timeout yang sama, jadi timer berjalan dari awal load.
     */
    private fun loadDashboard(url: String) {
        loadFailed = false
        loadTimeoutFired = false
        loadInProgress = true
        showLoadingOverlay()
        loadHandler.removeCallbacks(loadTimeoutRunnable)
        loadHandler.postDelayed(loadTimeoutRunnable, LOAD_TIMEOUT_MS)
        webView.loadUrl(url)
    }

    private fun retryLoad() {
        val url = prefs.getString(KEY_URL, null)
        if (!url.isNullOrBlank()) {
            loadDashboard(url)
        } else {
            webView.reload()
        }
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
        webView.webViewClient = object : WebViewClient() {
            override fun onPageStarted(view: WebView?, url: String?, favicon: Bitmap?) {
                loadInProgress = true
                loadFailed = false
                loadTimeoutFired = false
                hideErrorOverlay()
                showLoadingOverlay()
                loadHandler.removeCallbacks(loadTimeoutRunnable)
                loadHandler.postDelayed(loadTimeoutRunnable, LOAD_TIMEOUT_MS)
            }

            override fun onPageFinished(view: WebView?, url: String?) {
                loadHandler.removeCallbacks(loadTimeoutRunnable)
                loadInProgress = false
                // onPageFinished juga dipanggil setelah load gagal: jangan
                // sembunyikan overlay error yang sudah tampil.
                if (!loadFailed && !loadTimeoutFired) hideLoadingOverlay()
            }

            @Suppress("DEPRECATION")
            override fun onReceivedError(
                view: WebView?,
                errorCode: Int,
                description: String?,
                failingUrl: String?
            ) {
                // Overload lama: hanya dipanggil untuk main frame.
                markLoadFailed()
            }

            override fun onReceivedError(
                view: WebView?,
                request: WebResourceRequest?,
                error: WebResourceError?
            ) {
                // Overload baru: hanya main frame yang boleh memunculkan overlay error.
                if (request == null || request.isForMainFrame) markLoadFailed()
            }
        }
        webView.webChromeClient = object : WebChromeClient() {
            override fun onShowFileChooser(
                webView: WebView?,
                filePathCallback: ValueCallback<Array<Uri>>?,
                fileChooserParams: FileChooserParams?
            ): Boolean {
                // Batalkan chooser sebelumnya (jika ada) agar WebView tidak menggantung.
                fileChooserCallback?.onReceiveValue(null)
                fileChooserCallback = filePathCallback
                // GetContent() hanya menerima satu MIME: bila dashboard menerima
                // beberapa tipe (mis. image/*,video/*) pakai */* agar video tetap bisa dipilih.
                val types = fileChooserParams?.acceptTypes
                    ?.filter { it.isNotBlank() }
                    .orEmpty()
                val mime = if (types.size == 1) types[0] else "*/*"
                fileChooserLauncher.launch(mime)
                return true
            }

            override fun onShowCustomView(view: View?, callback: CustomViewCallback?) {
                if (customView != null) {
                    callback?.onCustomViewHidden()
                    return
                }
                val custom = view ?: run {
                    callback?.onCustomViewHidden()
                    return
                }
                customView = custom
                customViewCallback = callback
                val decor = window.decorView as android.view.ViewGroup
                val container = FrameLayout(this@MainActivity)
                container.addView(
                    custom,
                    FrameLayout.LayoutParams(
                        FrameLayout.LayoutParams.MATCH_PARENT,
                        FrameLayout.LayoutParams.MATCH_PARENT
                    )
                )
                decor.addView(
                    container,
                    FrameLayout.LayoutParams(
                        FrameLayout.LayoutParams.MATCH_PARENT,
                        FrameLayout.LayoutParams.MATCH_PARENT
                    )
                )
                fullscreenContainer = container
                webView.visibility = View.GONE
            }

            override fun onHideCustomView() {
                customView?.let { view ->
                    fullscreenContainer?.removeView(view)
                }
                val decor = window.decorView as android.view.ViewGroup
                fullscreenContainer?.let { decor.removeView(it) }
                fullscreenContainer = null
                customView = null
                webView.visibility = View.VISIBLE
                customViewCallback?.onCustomViewHidden()
                customViewCallback = null
            }
        }
        webView.addJavascriptInterface(KisaJsInterface(), "KisaApp")
        val theme = currentTheme()
        loadingOverlay = buildLoadingOverlay(theme)
        errorOverlay = buildErrorOverlay(theme)
        rootLayout = FrameLayout(this).apply {
            addView(
                webView,
                FrameLayout.LayoutParams(
                    FrameLayout.LayoutParams.MATCH_PARENT,
                    FrameLayout.LayoutParams.MATCH_PARENT
                )
            )
            addView(
                loadingOverlay,
                FrameLayout.LayoutParams(
                    FrameLayout.LayoutParams.MATCH_PARENT,
                    FrameLayout.LayoutParams.MATCH_PARENT
                )
            )
            addView(
                errorOverlay,
                FrameLayout.LayoutParams(
                    FrameLayout.LayoutParams.MATCH_PARENT,
                    FrameLayout.LayoutParams.MATCH_PARENT
                )
            )
        }
        setContentView(rootLayout)
        val url = prefs.getString(KEY_URL, null)
        if (url.isNullOrBlank()) askForAddress() else loadDashboard(url)
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

    override fun onDestroy() {
        loadHandler.removeCallbacks(loadTimeoutRunnable)
        addressDialog?.dismiss()
        addressDialog = null
        super.onDestroy()
    }

    private fun requestCameraAndScan() {
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA) ==
            PackageManager.PERMISSION_GRANTED
        ) {
            launchScanner()
        } else {
            permissionLauncher.launch(Manifest.permission.CAMERA)
        }
    }

    private fun launchScanner() {
        scanLauncher.launch(Intent(this, ScanActivity::class.java))
    }

    /**
     * Dialog alamat kustom S142 Cara 1 (kartu tengah), dibangun programatik
     * tanpa XML layout / drawable baru — mengikuti gaya ScanActivity.
     * Perilaku sama seperti AlertDialog lama: Hubungkan dengan input kosong
     * hanya menampilkan Toast dan dialog tetap terbuka.
     */
    private fun askForAddress() {
        addressDialog?.dismiss()
        val t = currentTheme()
        lateinit var dialog: Dialog
        val input = EditText(this).apply {
            hint = DEFAULT_HINT
            setText(prefs.getString(KEY_URL, "") ?: "")
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_URI
            setTextColor(t.text)
            setHintTextColor(t.secondary)
            textSize = 14f
            background = GradientDrawable().apply {
                shape = GradientDrawable.RECTANGLE
                cornerRadius = dp(8).toFloat()
                setColor(if (t.night) 0x14FFFFFF.toInt() else 0x0D000000.toInt())
                setStroke(dp(1), if (t.night) 0x24FFFFFF.toInt() else 0x24000000.toInt())
            }
            setPadding(dp(12), dp(10), dp(12), dp(10))
        }
        val card = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            background = cardBackground(t)
            setPadding(dp(18), dp(18), dp(18), dp(18))
            val title = TextView(this@MainActivity).apply {
                text = "Hubungkan ke PC"
                textSize = 16f
                setTypeface(typeface, Typeface.BOLD)
                setTextColor(t.text)
                gravity = Gravity.CENTER
            }
            addView(
                title,
                LinearLayout.LayoutParams(
                    LinearLayout.LayoutParams.MATCH_PARENT,
                    LinearLayout.LayoutParams.WRAP_CONTENT
                ).apply { bottomMargin = dp(4) }
            )
            val sub = TextView(this@MainActivity).apply {
                text = "Masukkan alamat dashboard di PC (satu Wi-Fi yang sama), atau scan QR code dashboard."
                textSize = 12f
                setTextColor(t.secondary)
                gravity = Gravity.CENTER
            }
            addView(
                sub,
                LinearLayout.LayoutParams(
                    LinearLayout.LayoutParams.MATCH_PARENT,
                    LinearLayout.LayoutParams.WRAP_CONTENT
                ).apply { bottomMargin = dp(12) }
            )
            addView(
                input,
                LinearLayout.LayoutParams(
                    LinearLayout.LayoutParams.MATCH_PARENT,
                    LinearLayout.LayoutParams.WRAP_CONTENT
                ).apply { bottomMargin = dp(10) }
            )
            val connect = primaryButton(t, "Hubungkan")
            connect.setOnClickListener {
                val url = input.text.toString().trim()
                if (url.isBlank()) {
                    Toast.makeText(this@MainActivity, "Alamat masih kosong.", Toast.LENGTH_SHORT).show()
                    return@setOnClickListener
                }
                prefs.edit().putString(KEY_URL, url).apply()
                dialog.dismiss()
                loadDashboard(url)
            }
            addView(connect, fullWidthParams(8))
            val scan = secondaryButton(t, "Scan QR", withIcon = true)
            scan.setOnClickListener {
                dialog.dismiss()
                requestCameraAndScan()
            }
            addView(scan, fullWidthParams(8))
            val cancel = textButton(t, "Batal")
            cancel.setOnClickListener { dialog.dismiss() }
            addView(
                cancel,
                LinearLayout.LayoutParams(
                    LinearLayout.LayoutParams.MATCH_PARENT,
                    LinearLayout.LayoutParams.WRAP_CONTENT
                ).apply { gravity = Gravity.CENTER_HORIZONTAL }
            )
        }
        val container = FrameLayout(this).apply {
            setPadding(dp(24), 0, dp(24), 0)
            addView(
                card,
                FrameLayout.LayoutParams(
                    FrameLayout.LayoutParams.MATCH_PARENT,
                    FrameLayout.LayoutParams.WRAP_CONTENT
                )
            )
        }
        dialog = Dialog(this).apply {
            setContentView(container)
            setCancelable(true)
            setCanceledOnTouchOutside(true)
            window?.apply {
                setBackgroundDrawable(ColorDrawable(Color.TRANSPARENT))
                setLayout(
                    ViewGroup.LayoutParams.MATCH_PARENT,
                    ViewGroup.LayoutParams.WRAP_CONTENT
                )
                setDimAmount(if (t.night) 0.55f else 0.35f)
            }
            setOnDismissListener { if (addressDialog === dialog) addressDialog = null }
        }
        addressDialog = dialog
        dialog.show()
    }

    @Deprecated("Dipakai untuk tombol kembali WebView.")
    override fun onBackPressed() {
        if (webView.canGoBack()) webView.goBack() else super.onBackPressed()
    }

    /**
     * Bridge JS untuk dashboard: window.KisaApp.setOrientation(mode).
     *
     * Signature: fun setOrientation(mode: String?)
     * Nilai mode (case-insensitive, spasi diabaikan):
     *   "landscape" -> SCREEN_ORIENTATION_LANDSCAPE
     *   "portrait"  -> SCREEN_ORIENTATION_PORTRAIT
     *   "auto"      -> SCREEN_ORIENTATION_UNSPECIFIED (ikut sensor/rotasi sistem)
     *   nilai lain / null / kosong -> SCREEN_ORIENTATION_UNSPECIFIED
     * Dashboard harus memanggil secara defensif (hanya jika window.KisaApp ada).
     */
    private inner class KisaJsInterface {
        @JavascriptInterface
        fun setOrientation(mode: String?) {
            val orientation = when (mode?.trim()?.lowercase()) {
                "landscape" -> ActivityInfo.SCREEN_ORIENTATION_LANDSCAPE
                "portrait" -> ActivityInfo.SCREEN_ORIENTATION_PORTRAIT
                "auto" -> ActivityInfo.SCREEN_ORIENTATION_UNSPECIFIED
                else -> ActivityInfo.SCREEN_ORIENTATION_UNSPECIFIED
            }
            runOnUiThread { requestedOrientation = orientation }
        }
    }

}
