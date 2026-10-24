package app.julz.settings

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import java.security.KeyStore
import java.util.Base64
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/** What the app connects to. SECURITY.md threats 88 and 94. */
object Settings {
    // The julz push server on my tailnet: https, a ts.net name, port 8444, nothing else
    private val SERVER = Regex("https://[a-z0-9-]{1,63}\\.[a-z0-9-]{1,63}\\.ts\\.net:8444")
    private val TOKEN = Regex("tk_[a-z0-9]{29}")

    fun validServer(url: String) = SERVER.matches(url)
    fun validToken(token: String) = TOKEN.matches(token)
}

/** Encrypts and decrypts with a key the caller never sees. */
interface Sealer {
    fun seal(plain: ByteArray): ByteArray
    fun open(sealed: ByteArray): ByteArray
}

/** AES-256-GCM with a key that lives in the Android Keystore and cannot be exported. Not bound
 *  to "phone unlocked": the service must read the token to reconnect while the phone is locked.
 *  The data is still in credential encrypted storage, unreadable before the first unlock. */
class KeystoreSealer : Sealer {
    private val key: SecretKey = run {
        val ks = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (ks.getKey(ALIAS, null) as? SecretKey) ?: KeyGenerator
            .getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
            .apply {
                init(KeyGenParameterSpec.Builder(ALIAS,
                    KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                    .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                    .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                    .setKeySize(256)
                    .build())
            }.generateKey()
    }

    override fun seal(plain: ByteArray): ByteArray {
        val c = Cipher.getInstance("AES/GCM/NoPadding").apply { init(Cipher.ENCRYPT_MODE, key) }
        return c.iv + c.doFinal(plain)
    }

    override fun open(sealed: ByteArray): ByteArray {
        val c = Cipher.getInstance("AES/GCM/NoPadding")
        c.init(Cipher.DECRYPT_MODE, key, GCMParameterSpec(128, sealed, 0, IV))
        return c.doFinal(sealed, IV, sealed.size - IV)
    }

    companion object {
        const val ALIAS = "julz-token"
        const val IV = 12

        /** Wipe: the key goes too, so a copy of the old ciphertext is useless. */
        fun deleteKey() {
            KeyStore.getInstance("AndroidKeyStore").apply { load(null) }.deleteEntry(ALIAS)
        }
    }
}

/** The phone token, stored only sealed. A token that does not open (tampered, other key) is
 *  treated as missing, never repaired. */
class TokenVault(private val sealer: Sealer, private val store: MutableMap<String, String>) {
    fun save(token: String): Boolean {
        if (!Settings.validToken(token)) return false
        store[KEY] = Base64.getEncoder().encodeToString(sealer.seal(token.toByteArray()))
        return true
    }

    fun load(): String? {
        val sealed = store[KEY] ?: return null
        val token = try {
            String(sealer.open(Base64.getDecoder().decode(sealed)))
        } catch (e: Exception) {  // bad base64, a failed GCM tag, another key
            return null
        }
        return token.takeIf { Settings.validToken(it) }
    }

    fun wipe() {
        store.remove(KEY)
    }

    companion object {
        const val KEY = "token"

        /** The app's private preferences as the store, nothing in backups (allowBackup off). */
        fun onDevice(context: Context): TokenVault {
            val prefs = context.getSharedPreferences("julz", Context.MODE_PRIVATE)
            val store = object : AbstractMutableMap<String, String>() {
                override val entries: MutableSet<MutableMap.MutableEntry<String, String>>
                    get() = prefs.all.filterValues { it is String }
                        .mapValues { it.value as String }.toMutableMap().entries
                override fun put(key: String, value: String): String? {
                    val old = prefs.getString(key, null)
                    prefs.edit().putString(key, value).commit()
                    return old
                }
                override fun remove(key: String): String? {
                    val old = prefs.getString(key, null)
                    prefs.edit().remove(key).commit()
                    return old
                }
            }
            return TokenVault(KeystoreSealer(), store)
        }
    }
}
