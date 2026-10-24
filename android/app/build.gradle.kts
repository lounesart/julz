plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.plugin.compose")
}

android {
    namespace = "app.julz"
    compileSdk = 37

    defaultConfig {
        applicationId = "app.julz"
        minSdk = 35 // my phone runs Android 15; no older phone to support
        targetSdk = 37
        versionCode = 1
        // The release tag, so Settings says what deploy.py says: v1.42, or v1.42-3-g1a2b3c4 on a branch (22d)
        // Outside a git tree (a copy for a mutation run) it says dev instead of failing the build
        versionName = providers.exec {
            commandLine("git", "describe", "--tags", "--match", "v*", "--always", "--dirty")
            isIgnoreExitValue = true
        }.standardOutput.asText.get().trim().ifEmpty { "dev" }
    }

    buildTypes {
        // No signingConfig on purpose: the release APK comes out unsigned and I sign it with
        // apksigner, so the key's password never reaches Gradle, a file or anyone else (96)
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"))
        }
    }

    buildFeatures {
        compose = true
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_21
        targetCompatibility = JavaVersion.VERSION_21
    }
}

dependencies {
    // Few libraries on purpose (threat 97): Compose, Activity, nothing from Firebase or Play
    implementation(platform("androidx.compose:compose-bom:2026.09.00"))
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.activity:activity-compose:1.13.0")
    implementation("androidx.browser:browser:1.10.0")  // Custom Tabs for chat and approver (94)
    // Tests only, never in the APK: org.json runs the parser on the laptop's JVM
    testImplementation("junit:junit:4.13.2")
    testImplementation("org.json:json:20260814")
}
