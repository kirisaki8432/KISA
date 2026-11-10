package com.kirisaki.kisa

import android.Manifest
import android.annotation.SuppressLint
import android.app.Dialog
import android.app.DownloadManager
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
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
import android.os.Build
import android.os.Bundle
import android.os.Environment
import android.os.Handler
import android.os.Looper
import android.text.InputType
import android.view.Gravity
import android.view.Menu
import android.view.MenuItem
import android.view.View
import android.view.ViewGroup
import android.view.Window
import android.view.WindowInsets
import android.view.WindowInsetsController
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
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.TextView
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.core.content.FileProvider
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
 * Patch 4.0: imersif penuh saat fullscreen (S149 Cara 2) — status bar +
 * tombol navigasi sistem disembunyikan total; hanya ⛶ lagi / Back yang
 * memunculkan.
 * Patch 4.2: dialog "Hubungkan ke PC" dirapikan (jarak rata, ikon + teks
 * "Scan QR" satu grup di tengah) + imersif dialog — bar HP disembunyikan
 * saat dialog tampil, ketuk layar = toggle tampil/sembunyi (tegak maupun
 * kesamping); bar kembali muncul saat dialog ditutup.
 * Patch 4.6: bridge JS KisaApp.downloadApk (S157 Cara 1) — unduh APK update
 * dari server PC lewat DownloadManager lalu pasang via FileProvider.
 */
class MainActivity : AppCompatActivity() {

    private lateinit var webView: WebView
    private lateinit var prefs: SharedPreferences
    private lateinit var rootLayout: FrameLayout
    private lateinit var loadingOverlay: LinearLayout
    private lateinit var errorOverlay: LinearLayout
    private var addressDialog: Dialog? = null
    // Patch 4.2: state imersif dialog "Hubungkan ke PC" — true = bar HP
    // sedang disembunyikan (toggle lewat ketuk layar).
    private var addressDialogBarsHidden = false

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
    // Patch 4.7 (S145 Cara 1): fullscreen aplikasi via bridge
    // dashboard (bukan via Fullscreen API browser).
    private var isAppFullscreen = false
    private var fullscreenContainer: FrameLayout? = null

    // ------------------------------------------------------------------
    // Imersif fullscreen (Patch 4.0, S149 Cara 2 — Imersif Penuh).
    //
    // Saat dashboard masuk fullscreen (tombol ⛶), status bar + tombol
    // navigasi sistem disembunyikan secara TOTAL (bukan lengket): usap
    // dari tepi masih bisa memunculkan bar sistem (perilaku Android yang
    // tidak bisa dicegah), tapi bar tidak disembunyikan lagi secara paksa
    // — tombol Back tetap bisa dipakai untuk keluar dari fullscreen. Bar
    // kembali normal saat fullscreen ditutup. Sengaja TIDAK ada listener
    // yang menyembunyikan ulang bar begitu muncul: itu akan membuat
    // tombol Back tidak bisa dijangkau.
    // ------------------------------------------------------------------

    // Patch 4.2: hide/show kini memakai helper berbasis Window agar bisa
    // dipakai juga untuk jendela Dialog "Hubungkan ke PC" (bukan hanya
    // jendela Activity). Perilaku S149 tidak berubah: non-sticky, usap
    // memunculkan bar dan bar TETAP tampil sampai disembunyikan lagi.
    @Suppress("DEPRECATION")
    private fun hideBarsOnWindow(win: Window) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            win.insetsController?.let { controller ->
                controller.hide(
                    WindowInsets.Type.statusBars() or WindowInsets.Type.navigationBars()
                )
                controller.systemBarsBehavior =
                    WindowInsetsController.BEHAVIOR_SHOW_BARS_BY_SWIPE
            }
        } else {
            win.decorView.systemUiVisibility = (
                View.SYSTEM_UI_FLAG_LAYOUT_STABLE
                    or View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION
                    or View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN
                    or View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
                    or View.SYSTEM_UI_FLAG_FULLSCREEN
                    or View.SYSTEM_UI_FLAG_IMMERSIVE
                )
            // SYSTEM_UI_FLAG_IMMERSIVE (tanpa STICKY): usap memunculkan
            // bar dan bar tetap tampil sampai disembunyikan lagi.
        }
    }

    @Suppress("DEPRECATION")
    private fun showBarsOnWindow(win: Window) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            win.insetsController?.show(
                WindowInsets.Type.statusBars() or WindowInsets.Type.navigationBars()
            )
        } else {
            win.decorView.systemUiVisibility = View.SYSTEM_UI_FLAG_LAYOUT_STABLE
        }
    }

    private fun hideSystemBars() = hideBarsOnWindow(window)

    private fun showSystemBars() = showBarsOnWindow(window)

    // Patch 4.2: toggle bar HP untuk dialog "Hubungkan ke PC" — ketuk layar
    // (di luar tombol/input) sekali muncul, sekali hilang; berlaku tegak
    // maupun kesamping. Ketuk pada tombol dialog tetap berfungsi normal
    // karena tombol mengonsumsi sentuhannya sendiri.
    private fun toggleAddressDialogBars() {
        val dialog = addressDialog ?: return
        addressDialogBarsHidden = !addressDialogBarsHidden
        if (addressDialogBarsHidden) {
            hideSystemBars()
            dialog.window?.let { hideBarsOnWindow(it) }
        } else {
            showSystemBars()
            dialog.window?.let { showBarsOnWindow(it) }
        }
    }

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

    private fun secondaryButton(t: ThemeColors, text: String, withIcon: Boolean = false): View {
        val bg = GradientDrawable().apply {
            shape = GradientDrawable.RECTANGLE
            cornerRadius = dp(10).toFloat()
            setColor(Color.TRANSPARENT)
            setStroke(dp(1), if (t.night) 0x38FFFFFF.toInt() else 0x38000000.toInt())
        }
        if (withIcon) {
            // Patch 4.2: ikon + teks SATU grup di tengah. Button biasa
            // menaruh compound drawable di kiri dan teks di tengah, jadi
            // ikon tampak jauh di kiri sementara teks di tengah (keluhan
            // user di screenshot dialog). Row ini memakai gravity CENTER
            // dengan tinggi minimum sama seperti tombol (48dp).
            return LinearLayout(this).apply {
                orientation = LinearLayout.HORIZONTAL
                gravity = Gravity.CENTER
                isClickable = true
                isFocusable = true
                background = bg
                backgroundTintList = null
                minimumHeight = dp(48)
                setPadding(dp(12), dp(11), dp(12), dp(11))
                // Ikon framework yang pasti ada (bukan drawable aplikasi).
                val icon = ContextCompat.getDrawable(
                    this@MainActivity, android.R.drawable.ic_menu_camera
                )?.mutate()
                if (icon != null) {
                    DrawableCompat.setTint(icon, t.text)
                    val iconView = ImageView(this@MainActivity).apply {
                        setImageDrawable(icon)
                    }
                    addView(
                        iconView,
                        LinearLayout.LayoutParams(dp(18), dp(18)).apply {
                            marginEnd = dp(7)
                        }
                    )
                }
                val label = TextView(this@MainActivity).apply {
                    this.text = text
                    textSize = 14f
                    setTypeface(typeface, Typeface.BOLD)
                    setTextColor(t.text)
                }
                addView(
                    label,
                    LinearLayout.LayoutParams(
                        LinearLayout.LayoutParams.WRAP_CONTENT,
                        LinearLayout.LayoutParams.WRAP_CONTENT
                    )
                )
            }
        }
        return Button(this).apply {
            this.text = text
            setAllCaps(false)
            textSize = 14f
            setTypeface(typeface, Typeface.BOLD)
            setTextColor(t.text)
            background = bg
            backgroundTintList = null
            setPadding(dp(12), dp(11), dp(12), dp(11))
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
            // Patch 4.2: minHeight default Button (48dp) membuat jarak
            // "Batal" ke tombol di atasnya tampak jauh lebih besar dari
            // jarak antar elemen lain — matikan agar jaraknya rata.
            minimumHeight = 0
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
                // Patch 4.0 (S149 Cara 2): sembunyikan status bar + tombol
                // navigasi sistem selama fullscreen.
                hideSystemBars()
            }

            override fun onHideCustomView() {
                // Patch 4.0 (S149 Cara 2): kembalikan bar sistem.
                showSystemBars()
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
     * Patch 4.2: jarak antar elemen rata (10dp), ikon + teks "Scan QR" satu
     * grup di tengah, dialog imersif (bar HP hilang, ketuk layar = toggle).
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
            addView(connect, fullWidthParams(10))
            val scan = secondaryButton(t, "Scan QR", withIcon = true)
            scan.setOnClickListener {
                dialog.dismiss()
                requestCameraAndScan()
            }
            addView(scan, fullWidthParams(10))
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
        // Patch 4.2: container selayar penuh dengan kartu di tengah — ketuk
        // di mana saja di luar tombol/input (judul, subjudul, celah, area
        // redup) = toggle bar HP. Tombol/input mengonsumsi sentuhannya
        // sendiri sehingga tetap berfungsi normal.
        val container = FrameLayout(this).apply {
            setPadding(dp(24), 0, dp(24), 0)
            setOnClickListener { toggleAddressDialogBars() }
            addView(
                card,
                FrameLayout.LayoutParams(
                    FrameLayout.LayoutParams.MATCH_PARENT,
                    FrameLayout.LayoutParams.WRAP_CONTENT,
                    Gravity.CENTER
                )
            )
        }
        dialog = Dialog(this).apply {
            setContentView(container)
            setCancelable(true)
            // Patch 4.2: ketuk di luar kartu = toggle bar HP, bukan tutup
            // dialog (tutup lewat "Batal" atau Back).
            setCanceledOnTouchOutside(false)
            window?.apply {
                setBackgroundDrawable(ColorDrawable(Color.TRANSPARENT))
                setLayout(
                    ViewGroup.LayoutParams.MATCH_PARENT,
                    ViewGroup.LayoutParams.MATCH_PARENT
                )
                setDimAmount(if (t.night) 0.55f else 0.35f)
            }
            setOnDismissListener {
                if (addressDialog === dialog) addressDialog = null
                // Patch 4.2: bar HP kembali normal saat dialog ditutup.
                addressDialogBarsHidden = false
                showSystemBars()
            }
        }
        addressDialog = dialog
        dialog.show()
        // Patch 4.2: imersif saat dialog tampil (tegak maupun kesamping).
        addressDialogBarsHidden = true
        hideSystemBars()
        dialog.window?.let { hideBarsOnWindow(it) }
        // Jendela dialog baru terpasang setelah show() — pasang lagi begitu
        // decorView siap, supaya bar benar-benar hilang.
        dialog.window?.decorView?.post {
            if (addressDialog === dialog && addressDialogBarsHidden) {
                dialog.window?.let { hideBarsOnWindow(it) }
            }
        }
    }

    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        // Patch 4.0 (S149 Cara 2): pergantian fokus (mis. kembali dari
        // dialog sistem) bisa menghapus flag imersif — pasang lagi selama
        // masih fullscreen.
        if (hasFocus && (customView != null || isAppFullscreen)) hideSystemBars()
    }

    @Deprecated("Dipakai untuk tombol kembali WebView.")
    override fun onBackPressed() {
        // Patch 4.0 (S149 Cara 2): saat fullscreen, Back keluar dari
        // fullscreen dulu — bukan mundur halaman / menutup aplikasi.
        if (customView != null) {
            webView.webChromeClient?.onHideCustomView()
            return
        }
        // Patch 4.7 (S145 Cara 1): Back keluar dari fullscreen aplikasi
        // dulu — bukan mundur halaman / menutup aplikasi. Beri tahu
        // dashboard lewat hook supaya ikon fullscreen ikut tersinkron.
        if (isAppFullscreen) {
            isAppFullscreen = false
            showSystemBars()
            webView.evaluateJavascript("window.__kisaAppFsExit && window.__kisaAppFsExit();", null)
            return
        }
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

        /**
         * Bridge JS untuk dashboard (Patch 4.7, S145 Cara 1): fullscreen
         * asli di aplikasi (tanpa title bar / status bar / nav bar).
         *
         * Signature: fun setFullscreen(on: Boolean)
         * on=true  -> sembunyikan bar sistem (pakai helper S149 yang
         *             sudah ada: non-sticky, usap memunculkan bar).
         * on=false -> kembalikan bar sistem.
         * Back keluar dari fullscreen ditangani onBackPressed (bukan di
         * sini) supaya ikon dashboard ikut tersinkron lewat hook
         * window.__kisaAppFsExit.
         * Dashboard harus memanggil secara defensif (hanya jika
         * window.KisaApp ada).
         */
        @JavascriptInterface
        fun setFullscreen(on: Boolean) {
            runOnUiThread {
                isAppFullscreen = on
                if (on) hideSystemBars() else showSystemBars()
            }
        }

        /**
         * Bridge JS untuk dashboard (Patch 4.6, S157 Cara 1): unduh APK
         * update dari server PC lalu pasang.
         *
         * Signature: fun downloadApk(url: String?, fileName: String?)
         * url = alamat file APK di server PC
         * (mis. http://192.168.1.10:8000/api/update_file?name=KISA-4.6.apk).
         * fileName = nama file APK (harus berakhiran .apk, tanpa path).
         * Alur: DownloadManager mengunduh ke Download/KISA/ -> saat selesai,
         * intent instal dibuka lewat FileProvider. Android TETAP minta user
         * mengizinkan "instal aplikasi tidak dikenal" sekali + mengetuk
         * Instal — tidak bisa pasang diam-diam.
         * Dashboard harus memanggil secara defensif (hanya jika window.KisaApp ada).
         */
        @JavascriptInterface
        fun downloadApk(url: String?, fileName: String?) {
            val cleanUrl = url?.trim().orEmpty()
            val cleanName = fileName?.trim().orEmpty()
            if (cleanUrl.isEmpty() || !(cleanUrl.startsWith("http://") || cleanUrl.startsWith("https://"))) return
            if (cleanName.isEmpty() || !cleanName.endsWith(".apk") || cleanName.contains("/") || cleanName.contains("\\")) return
            runOnUiThread {
                Toast.makeText(this@MainActivity, "Mengunduh update KISA…", Toast.LENGTH_SHORT).show()
            }
            try {
                val dm = getSystemService(Context.DOWNLOAD_SERVICE) as DownloadManager
                val req = DownloadManager.Request(Uri.parse(cleanUrl))
                    .setTitle("KISA update")
                    .setDescription(cleanName)
                    .setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED)
                    .setMimeType("application/vnd.android.package-archive")
                    .setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, "KISA/$cleanName")
                val dlId = dm.enqueue(req)
                val filter = IntentFilter(DownloadManager.ACTION_DOWNLOAD_COMPLETE)
                val receiver = object : BroadcastReceiver() {
                    override fun onReceive(context: Context?, intent: Intent?) {
                        val doneId = intent?.getLongExtra(DownloadManager.EXTRA_DOWNLOAD_ID, -1L) ?: -1L
                        if (doneId != dlId) return
                        try { unregisterReceiver(this) } catch (e: Exception) { }
                        try {
                            val q = DownloadManager.Query().setFilterById(dlId)
                            val cursor = dm.query(q)
                            var ok = false
                            var localUri: String? = null
                            cursor?.use {
                                if (it.moveToFirst()) {
                                    val status = it.getInt(it.getColumnIndexOrThrow(DownloadManager.COLUMN_STATUS))
                                    ok = status == DownloadManager.STATUS_SUCCESSFUL
                                    localUri = it.getString(it.getColumnIndexOrThrow(DownloadManager.COLUMN_LOCAL_URI))
                                }
                            }
                            if (!ok) {
                                runOnUiThread { Toast.makeText(this@MainActivity, "Unduhan update gagal.", Toast.LENGTH_LONG).show() }
                                return
                            }
                            val file = java.io.File(Uri.parse(localUri).path ?: "")
                            if (!file.exists()) {
                                runOnUiThread { Toast.makeText(this@MainActivity, "File update tidak ditemukan.", Toast.LENGTH_LONG).show() }
                                return
                            }
                            val contentUri = FileProvider.getUriForFile(this@MainActivity, "${packageName}.fileprovider", file)
                            val install = Intent(Intent.ACTION_VIEW).apply {
                                setDataAndType(contentUri, "application/vnd.android.package-archive")
                                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_GRANT_READ_URI_PERMISSION)
                            }
                            startActivity(install)
                        } catch (e: Exception) {
                            runOnUiThread { Toast.makeText(this@MainActivity, "Gagal memasang update.", Toast.LENGTH_LONG).show() }
                        }
                    }
                }
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                    ContextCompat.registerReceiver(this@MainActivity, receiver, filter, ContextCompat.RECEIVER_NOT_EXPORTED)
                } else {
                    registerReceiver(receiver, filter)
                }
            } catch (e: Exception) {
                runOnUiThread { Toast.makeText(this@MainActivity, "Gagal mengunduh update.", Toast.LENGTH_LONG).show() }
            }
        }
    }

}
