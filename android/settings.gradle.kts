// Julz phone app. Plan: PLAN.md "Phone app". Threats 86 to 101: SECURITY.md.
pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}

dependencyResolutionManagement {
    // Libraries come only from these two, never from a repository a module adds (threat 97)
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        mavenCentral()
    }
}

rootProject.name = "julz-phone"
include(":app")
