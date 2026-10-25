// Versions pinned here; every downloaded file is checked against gradle/verification-metadata.xml
plugins {
    id("com.android.application") version "9.4.1" apply false
    id("org.jetbrains.kotlin.plugin.compose") version "2.4.21" apply false
    // Screenshot tests only (184, threat 150): runs in the build, so pinned and hash checked too
    id("app.cash.paparazzi") version "2.0.0-alpha05.1" apply false
}
