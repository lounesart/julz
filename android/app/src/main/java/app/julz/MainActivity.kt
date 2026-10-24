package app.julz

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Bundle
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import app.julz.settings.ConfigStore
import app.julz.ui.App

class MainActivity : ComponentActivity() {
    private var version by mutableIntStateOf(0)
    private var opened by mutableStateOf<Notifier.Target?>(null)
    private var openedFilter by mutableStateOf<app.julz.feed.Kind?>(null)
    // The screen in front: the service leaves its notices out of the tray only while resumed
    private var showing: Notifier.Target? = null
    private var resumed = false

    private val askNotify = registerForActivityResult(ActivityResultContracts.RequestPermission()) {
        JulzService.start(this)
        version++
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        app.julz.ui.A11y.load(this)
        app.julz.ui.Look.load(this)
        app.julz.ui.ChatPrefs.load(this)
        // No screenshots, a blank recent apps preview (threat 89). Debug builds skip it so the
        // screens can be checked during development; a release always sets it
        if (!DebugOnly.enabled(this)) window.setFlags(WindowManager.LayoutParams.FLAG_SECURE, WindowManager.LayoutParams.FLAG_SECURE)
        // A rebuilt activity gets its first intent again: that tap was already followed
        if (savedInstanceState == null) follow(intent)
        setContent {
            App(version, opened, openedFilter, { opened = null }, { showing = it; if (resumed) Notifier.onScreen = it }, onSaved = {
                if (ConfigStore.load(this) != null &&
                    checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
                    askNotify.launch(Manifest.permission.POST_NOTIFICATIONS)
                } else {
                    if (ConfigStore.load(this) != null) JulzService.start(this)
                    version++
                }
            })
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        follow(intent)
    }

    /** A notification tap opens its kind's screen (13d). Opening from recent apps replays the
     *  old intent, so that is skipped (threat 133 for what the extra may hold). */
    private fun follow(intent: Intent?) {
        if (intent == null || intent.flags and Intent.FLAG_ACTIVITY_LAUNCHED_FROM_HISTORY != 0) return
        // A bad bundle from another app throws on unparcel: then there is no target, not a crash
        val name = runCatching { intent.getStringExtra(Notifier.EXTRA_KIND) }.getOrNull()
        openedFilter = Notifier.filter(name)
        opened = Notifier.target(name)
    }

    override fun onPause() {
        super.onPause()
        resumed = false
        Notifier.onScreen = null
    }

    // The launcher icon switches when I leave Julz (135): disabling the alias this task was started
    // with closes the task, so doing it while Julz is open threw me out of the app (found 18 Oct)
    override fun onStop() {
        super.onStop()
        app.julz.ui.LauncherIcon.apply(this, app.julz.ui.Look.prefs)
    }

    override fun onResume() {
        super.onResume()
        resumed = true
        Notifier.onScreen = showing
        JulzService.markSeen(this)
        Notifier.clear(this)
        // After an update or a kill the service is not running: opening the app starts it
        if (ConfigStore.load(this) != null && !JulzService.refused(this)) JulzService.start(this)
        version++
    }
}
