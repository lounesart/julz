package app.julz

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import app.julz.settings.ConfigStore

/** Starts the service after a reboot or an update of the app. Not exported: only the system
 *  sends these. It reads nothing from the intent but its action (SECURITY.md threat 99). */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != Intent.ACTION_BOOT_COMPLETED &&
            intent.action != Intent.ACTION_MY_PACKAGE_REPLACED) return
        if (ConfigStore.load(context) != null && !JulzService.refused(context)) JulzService.start(context)
    }
}
