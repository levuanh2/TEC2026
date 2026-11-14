import java.util.Properties

plugins {
    id("com.android.application")
    // The Flutter Gradle Plugin must be applied after the Android and Kotlin Gradle plugins.
    id("dev.flutter.flutter-gradle-plugin")
}

// Khoá ký release: đọc từ android/key.properties (gitignored) hoặc biến môi
// trường AGRICARBON_KEYSTORE_* — KHÔNG bao giờ để mật khẩu trong file này.
// Thiếu cấu hình thì bản release DỪNG build, không lặng lẽ ký bằng debug key.
val keystoreProperties = Properties().apply {
    val file = rootProject.file("key.properties")
    if (file.exists()) file.inputStream().use { load(it) }
}
fun signingValue(property: String, env: String): String? =
    keystoreProperties.getProperty(property) ?: System.getenv(env)
val releaseStoreFile = signingValue("storeFile", "AGRICARBON_KEYSTORE_PATH")
val hasReleaseSigning = releaseStoreFile != null && file(releaseStoreFile).exists()

// Bản QA cài song song với app thật: CHỈ debug, chọn bằng
// `flutter build apk --debug -P agricarbon.qaVariant=uipreview|localqa`.
// Không có property thì debug/release giữ nguyên applicationId vn.agricarbon.mobile.
val qaVariants = mapOf("uipreview" to "AgriCarbon Preview", "localqa" to "AgriCarbon QA")
val qaVariant = (findProperty("agricarbon.qaVariant") as String?)?.trim()?.takeIf { it.isNotEmpty() }
if (qaVariant != null && qaVariant !in qaVariants) {
    throw GradleException("agricarbon.qaVariant must be one of ${qaVariants.keys}, got '$qaVariant'")
}

android {
    namespace = "vn.agricarbon.mobile"
    compileSdk = flutter.compileSdkVersion
    ndkVersion = flutter.ndkVersion

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    defaultConfig {
        // TODO: Specify your own unique Application ID (https://developer.android.com/studio/build/application-id.html).
        applicationId = "vn.agricarbon.mobile"
        // You can update the following values to match your application needs.
        // For more information, see: https://flutter.dev/to/review-gradle-config.
        minSdk = flutter.minSdkVersion
        targetSdk = flutter.targetSdkVersion
        // Uses the version code from pubspec.yaml. When using split APKs, 1000 * ABI_VERSION
        // is added automatically by Flutter. (https://developer.android.com/studio/build/configure-apk-splits#configure-APK-versions)
        // You can force using the value of versionCode by specifying the `-P force-version-code-ignoring-abi=true`
        // flag during build.
        versionCode = flutter.versionCode
        versionName = flutter.versionName
        manifestPlaceholders["appLabel"] = "AgriCarbon"
    }

    signingConfigs {
        if (hasReleaseSigning) {
            create("release") {
                storeFile = file(releaseStoreFile!!)
                storePassword = signingValue("storePassword", "AGRICARBON_KEYSTORE_PASSWORD")
                keyAlias = signingValue("keyAlias", "AGRICARBON_KEY_ALIAS")
                keyPassword = signingValue("keyPassword", "AGRICARBON_KEY_PASSWORD")
            }
        }
    }

    buildTypes {
        debug {
            if (qaVariant != null) {
                applicationIdSuffix = ".$qaVariant"
                manifestPlaceholders["appLabel"] = qaVariants.getValue(qaVariant)
            }
        }
        release {
            if (hasReleaseSigning) {
                signingConfig = signingConfigs.getByName("release")
            }
        }
    }
}

gradle.taskGraph.whenReady {
    val buildsRelease = allTasks.any { it.project == project && it.name.contains("Release") }
    if (buildsRelease && qaVariant != null) {
        throw GradleException("agricarbon.qaVariant is for debug QA builds only, never release.")
    }
    if (buildsRelease && !hasReleaseSigning) {
        throw GradleException(
            "Release signing is not configured: create android/key.properties " +
                "(storeFile, storePassword, keyAlias, keyPassword) or set AGRICARBON_KEYSTORE_*. " +
                "A release build is never signed with the debug key."
        )
    }
}

kotlin {
    compilerOptions {
        jvmTarget = org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17
    }
}

flutter {
    source = "../.."
}
