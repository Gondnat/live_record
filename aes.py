import base64
from math import ceil
import struct
import sys

try:
    from Cryptodome.Cipher import AES
except ImportError:
    try:
        from Crypto.Cipher import AES
    except ImportError:
        AES = None

def compat_ord(c):
    return c if isinstance(c, int) else ord(c)

def bytes_to_intlist(bs):
    if not bs:
        return []
    if isinstance(bs[0], int):  # Python 3
        return list(bs)
    else:
        return [ord(c) for c in bs]


def intlist_to_bytes(xs):
    if not xs:
        return b''
    return struct.pack('%dB' % len(xs), *xs)

if AES:
    def aes_cbc_decrypt_bytes(data, key, iv):
        """ Decrypt bytes with AES-CBC using pycryptodome """
        return AES.new(key, AES.MODE_CBC, iv).decrypt(data)

    def aes_gcm_decrypt_and_verify_bytes(data, key, tag, nonce):
        """ Decrypt bytes with AES-GCM using pycryptodome """
        return AES.new(key, AES.MODE_GCM, nonce).decrypt_and_verify(data, tag)

else:
    def aes_cbc_decrypt_bytes(data, key, iv):
        """ Decrypt bytes with AES-CBC using native implementation since pycryptodome is unavailable """
        return intlist_to_bytes(aes_cbc_decrypt(*map(bytes_to_intlist, (data, key, iv))))

    def aes_gcm_decrypt_and_verify_bytes(data, key, tag, nonce):
        """ Decrypt bytes with AES-GCM using native implementation since pycryptodome is unavailable """
        return intlist_to_bytes(aes_gcm_decrypt_and_verify(*map(bytes_to_intlist, (data, key, tag, nonce))))


def aes_cbc_encrypt_bytes(data, key, iv, **kwargs):
    return intlist_to_bytes(aes_cbc_encrypt(*map(bytes_to_intlist, (data, key, iv)), **kwargs))


BLOCK_SIZE_BYTES = 16


def unpad_pkcs7(data):
    return data[:-compat_ord(data[-1])]


def pkcs7_padding(data):
    """
    PKCS#7 padding

    @param {int[]} data        cleartext
    @returns {int[]}           padding data
    """

    remaining_length = BLOCK_SIZE_BYTES - len(data) % BLOCK_SIZE_BYTES
    return data + [remaining_length] * remaining_length


def pad_block(block, padding_mode):
    """
    Pad a block with the given padding mode
    @param {int[]} block        block to pad
    @param padding_mode         padding mode
    """
    padding_size = BLOCK_SIZE_BYTES - len(block)

    PADDING_BYTE = {
        'pkcs7': padding_size,
        'iso7816': 0x0,
        'whitespace': 0x20,
        'zero': 0x0,
    }

    if padding_size < 0:
        raise ValueError('Block size exceeded')
    elif padding_mode not in PADDING_BYTE:
        raise NotImplementedError(f'Padding mode {padding_mode} is not implemented')

    if padding_mode == 'iso7816' and padding_size:
        block = [*block, 0x80]  # NB: += mutates list
        padding_size -= 1

    return block + [PADDING_BYTE[padding_mode]] * padding_size


def aes_ecb_encrypt(data, key, iv=None):
    """
    Encrypt with aes in ECB mode. Using PKCS#7 padding

    @param {int[]} data        cleartext
    @param {int[]} key         16/24/32-Byte cipher key
    @param {int[]} iv          Unused for this mode
    @returns {int[]}           encrypted data
    """
    expanded_key = key_expansion(key)
    block_count = int(ceil(float(len(data)) / BLOCK_SIZE_BYTES))

    encrypted_data = []
    for i in range(block_count):
        block = data[i * BLOCK_SIZE_BYTES: (i + 1) * BLOCK_SIZE_BYTES]
        encrypted_data += aes_encrypt(pkcs7_padding(block), expanded_key)

    return encrypted_data


def aes_ecb_decrypt(data, key, iv=None):
    """
    Decrypt with aes in ECB mode

    @param {int[]} data        cleartext
    @param {int[]} key         16/24/32-Byte cipher key
    @param {int[]} iv          Unused for this mode
    @returns {int[]}           decrypted data
    """
    expanded_key = key_expansion(key)
    block_count = int(ceil(float(len(data)) / BLOCK_SIZE_BYTES))

    encrypted_data = []
    for i in range(block_count):
        block = data[i * BLOCK_SIZE_BYTES: (i + 1) * BLOCK_SIZE_BYTES]
        encrypted_data += aes_decrypt(block, expanded_key)
    return encrypted_data[:len(data)]


def aes_ctr_decrypt(data, key, iv):
    """
    Decrypt with aes in counter mode

    @param {int[]} data        cipher
    @param {int[]} key         16/24/32-Byte cipher key
    @param {int[]} iv          16-Byte initialization vector
    @returns {int[]}           decrypted data
    """
    return aes_ctr_encrypt(data, key, iv)


def aes_ctr_encrypt(data, key, iv):
    """
    Encrypt with aes in counter mode

    @param {int[]} data        cleartext
    @param {int[]} key         16/24/32-Byte cipher key
    @param {int[]} iv          16-Byte initialization vector
    @returns {int[]}           encrypted data
    """
    expanded_key = key_expansion(key)
    block_count = int(ceil(float(len(data)) / BLOCK_SIZE_BYTES))
    counter = iter_vector(iv)

    encrypted_data = []
    for i in range(block_count):
        counter_block = next(counter)
        block = data[i * BLOCK_SIZE_BYTES: (i + 1) * BLOCK_SIZE_BYTES]
        block += [0] * (BLOCK_SIZE_BYTES - len(block))

        cipher_counter_block = aes_encrypt(counter_block, expanded_key)
        encrypted_data += xor(block, cipher_counter_block)
    return encrypted_data[:len(data)]


def aes_cbc_decrypt(data, key, iv):
    """
    Decrypt with aes in CBC mode

    @param {int[]} data        cipher
    @param {int[]} key         16/24/32-Byte cipher key
    @param {int[]} iv          16-Byte IV
    @returns {int[]}           decrypted data
    """
    expanded_key = key_expansion(key)
    block_count = int(ceil(float(len(data)) / BLOCK_SIZE_BYTES))

    decrypted_data = []
    previous_cipher_block = iv
    for i in range(block_count):
        block = data[i * BLOCK_SIZE_BYTES: (i + 1) * BLOCK_SIZE_BYTES]
        block += [0] * (BLOCK_SIZE_BYTES - len(block))

        decrypted_block = aes_decrypt(block, expanded_key)
        decrypted_data += xor(decrypted_block, previous_cipher_block)
        previous_cipher_block = block
    return decrypted_data[:len(data)]


def aes_cbc_encrypt(data, key, iv, *, padding_mode='pkcs7'):
    """
    Encrypt with aes in CBC mode

    @param {int[]} data        cleartext
    @param {int[]} key         16/24/32-Byte cipher key
    @param {int[]} iv          16-Byte IV
    @param padding_mode        Padding mode to use
    @returns {int[]}           encrypted data
    """
    expanded_key = key_expansion(key)
    block_count = int(ceil(float(len(data)) / BLOCK_SIZE_BYTES))

    encrypted_data = []
    previous_cipher_block = iv
    for i in range(block_count):
        block = data[i * BLOCK_SIZE_BYTES: (i + 1) * BLOCK_SIZE_BYTES]
        block = pad_block(block, padding_mode)

        mixed_block = xor(block, previous_cipher_block)

        encrypted_block = aes_encrypt(mixed_block, expanded_key)
        encrypted_data += encrypted_block

        previous_cipher_block = encrypted_block

    return encrypted_data


def aes_gcm_decrypt_and_verify(data, key, tag, nonce):
    """
    Decrypt with aes in GBM mode and checks authenticity using tag

    @param {int[]} data        cipher
    @param {int[]} key         16-Byte cipher key
    @param {int[]} tag         authentication tag
    @param {int[]} nonce       IV (recommended 12-Byte)
    @returns {int[]}           decrypted data
    """

    # XXX: check aes, gcm param

    hash_subkey = aes_encrypt([0] * BLOCK_SIZE_BYTES, key_expansion(key))

    if len(nonce) == 12:
        j0 = [*nonce, 0, 0, 0, 1]
    else:
        fill = (BLOCK_SIZE_BYTES - (len(nonce) % BLOCK_SIZE_BYTES)) % BLOCK_SIZE_BYTES + 8
        ghash_in = nonce + [0] * fill + bytes_to_intlist((8 * len(nonce)).to_bytes(8, 'big'))
        j0 = ghash(hash_subkey, ghash_in)

    # TODO: add nonce support to aes_ctr_decrypt

    # nonce_ctr = j0[:12]
    iv_ctr = inc(j0)

    decrypted_data = aes_ctr_decrypt(data, key, iv_ctr + [0] * (BLOCK_SIZE_BYTES - len(iv_ctr)))
    pad_len = (BLOCK_SIZE_BYTES - (len(data) % BLOCK_SIZE_BYTES)) % BLOCK_SIZE_BYTES
    s_tag = ghash(
        hash_subkey,
        data
        + [0] * pad_len                                         # pad
        + bytes_to_intlist((0 * 8).to_bytes(8, 'big')           # length of associated data
                           + ((len(data) * 8).to_bytes(8, 'big'))),  # length of data
    )

    if tag != aes_ctr_encrypt(s_tag, key, j0):
        raise ValueError('Mismatching authentication tag')

    return decrypted_data


def aes_encrypt(data, expanded_key):
    """
    Encrypt one block with aes

    @param {int[]} data          16-Byte state
    @param {int[]} expanded_key  176/208/240-Byte expanded key
    @returns {int[]}             16-Byte cipher
    """
    rounds = len(expanded_key) // BLOCK_SIZE_BYTES - 1

    data = xor(data, expanded_key[:BLOCK_SIZE_BYTES])
    for i in range(1, rounds + 1):
        data = sub_bytes(data)
        data = shift_rows(data)
        if i != rounds:
            data = list(iter_mix_columns(data, MIX_COLUMN_MATRIX))
        data = xor(data, expanded_key[i * BLOCK_SIZE_BYTES: (i + 1) * BLOCK_SIZE_BYTES])

    return data


def aes_decrypt(data, expanded_key):
    """
    Decrypt one block with aes

    @param {int[]} data          16-Byte cipher
    @param {int[]} expanded_key  176/208/240-Byte expanded key
    @returns {int[]}             16-Byte state
    """
    rounds = len(expanded_key) // BLOCK_SIZE_BYTES - 1

    for i in range(rounds, 0, -1):
        data = xor(data, expanded_key[i * BLOCK_SIZE_BYTES: (i + 1) * BLOCK_SIZE_BYTES])
        if i != rounds:
            data = list(iter_mix_columns(data, MIX_COLUMN_MATRIX_INV))
        data = shift_rows_inv(data)
        data = sub_bytes_inv(data)
    return xor(data, expanded_key[:BLOCK_SIZE_BYTES])


def aes_decrypt_text(data, password, key_size_bytes):
    """
    Decrypt text
    - The first 8 Bytes of decoded 'data' are the 8 high Bytes of the counter
    - The cipher key is retrieved by encrypting the first 16 Byte of 'password'
      with the first 'key_size_bytes' Bytes from 'password' (if necessary filled with 0's)
    - Mode of operation is 'counter'

    @param {str} data                    Base64 encoded string
    @param {str,unicode} password        Password (will be encoded with utf-8)
    @param {int} key_size_bytes          Possible values: 16 for 128-Bit, 24 for 192-Bit or 32 for 256-Bit
    @returns {str}                       Decrypted data
    """
    NONCE_LENGTH_BYTES = 8

    data = bytes_to_intlist(base64.b64decode(data))
    password = bytes_to_intlist(password.encode())

    key = password[:key_size_bytes] + [0] * (key_size_bytes - len(password))
    key = aes_encrypt(key[:BLOCK_SIZE_BYTES], key_expansion(key)) * (key_size_bytes // BLOCK_SIZE_BYTES)

    nonce = data[:NONCE_LENGTH_BYTES]
    cipher = data[NONCE_LENGTH_BYTES:]

    decrypted_data = aes_ctr_decrypt(cipher, key, nonce + [0] * (BLOCK_SIZE_BYTES - NONCE_LENGTH_BYTES))
    return intlist_to_bytes(decrypted_data)


RCON = (0x8d, 0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1b, 0x36)
SBOX = (0x63, 0x7C, 0x77, 0x7B, 0xF2, 0x6B, 0x6F, 0xC5, 0x30, 0x01, 0x67, 0x2B, 0xFE, 0xD7, 0xAB, 0x76,
        0xCA, 0x82, 0xC9, 0x7D, 0xFA, 0x59, 0x47, 0xF0, 0xAD, 0xD4, 0xA2, 0xAF, 0x9C, 0xA4, 0x72, 0xC0,
        0xB7, 0xFD, 0x93, 0x26, 0x36, 0x3F, 0xF7, 0xCC, 0x34, 0xA5, 0xE5, 0xF1, 0x71, 0xD8, 0x31, 0x15,
        0x04, 0xC7, 0x23, 0xC3, 0x18, 0x96, 0x05, 0x9A, 0x07, 0x12, 0x80, 0xE2, 0xEB, 0x27, 0xB2, 0x75,
        0x09, 0x83, 0x2C, 0x1A, 0x1B, 0x6E, 0x5A, 0xA0, 0x52, 0x3B, 0xD6, 0xB3, 0x29, 0xE3, 0x2F, 0x84,
        0x53, 0xD1, 0x00, 0xED, 0x20, 0xFC, 0xB1, 0x5B, 0x6A, 0xCB, 0xBE, 0x39, 0x4A, 0x4C, 0x58, 0xCF,
        0xD0, 0xEF, 0xAA, 0xFB, 0x43, 0x4D, 0x33, 0x85, 0x45, 0xF9, 0x02, 0x7F, 0x50, 0x3C, 0x9F, 0xA8,
        0x51, 0xA3, 0x40, 0x8F, 0x92, 0x9D, 0x38, 0xF5, 0xBC, 0xB6, 0xDA, 0x21, 0x10, 0xFF, 0xF3, 0xD2,
        0xCD, 0x0C, 0x13, 0xEC, 0x5F, 0x97, 0x44, 0x17, 0xC4, 0xA7, 0x7E, 0x3D, 0x64, 0x5D, 0x19, 0x73,
        0x60, 0x81, 0x4F, 0xDC, 0x22, 0x2A, 0x90, 0x88, 0x46, 0xEE, 0xB8, 0x14, 0xDE, 0x5E, 0x0B, 0xDB,
        0xE0, 0x32, 0x3A, 0x0A, 0x49, 0x06, 0x24, 0x5C, 0xC2, 0xD3, 0xAC, 0x62, 0x91, 0x95, 0xE4, 0x79,
        0xE7, 0xC8, 0x37, 0x6D, 0x8D, 0xD5, 0x4E, 0xA9, 0x6C, 0x56, 0xF4, 0xEA, 0x65, 0x7A, 0xAE, 0x08,
        0xBA, 0x78, 0x25, 0x2E, 0x1C, 0xA6, 0xB4, 0xC6, 0xE8, 0xDD, 0x74, 0x1F, 0x4B, 0xBD, 0x8B, 0x8A,
        0x70, 0x3E, 0xB5, 0x66, 0x48, 0x03, 0xF6, 0x0E, 0x61, 0x35, 0x57, 0xB9, 0x86, 0xC1, 0x1D, 0x9E,
        0xE1, 0xF8, 0x98, 0x11, 0x69, 0xD9, 0x8E, 0x94, 0x9B, 0x1E, 0x87, 0xE9, 0xCE, 0x55, 0x28, 0xDF,
        0x8C, 0xA1, 0x89, 0x0D, 0xBF, 0xE6, 0x42, 0x68, 0x41, 0x99, 0x2D, 0x0F, 0xB0, 0x54, 0xBB, 0x16)
SBOX_INV = (0x52, 0x09, 0x6a, 0xd5, 0x30, 0x36, 0xa5, 0x38, 0xbf, 0x40, 0xa3, 0x9e, 0x81, 0xf3, 0xd7, 0xfb,
            0x7c, 0xe3, 0x39, 0x82, 0x9b, 0x2f, 0xff, 0x87, 0x34, 0x8e, 0x43, 0x44, 0xc4, 0xde, 0xe9, 0xcb,
            0x54, 0x7b, 0x94, 0x32, 0xa6, 0xc2, 0x23, 0x3d, 0xee, 0x4c, 0x95, 0x0b, 0x42, 0xfa, 0xc3, 0x4e,
            0x08, 0x2e, 0xa1, 0x66, 0x28, 0xd9, 0x24, 0xb2, 0x76, 0x5b, 0xa2, 0x49, 0x6d, 0x8b, 0xd1, 0x25,
            0x72, 0xf8, 0xf6, 0x64, 0x86, 0x68, 0x98, 0x16, 0xd4, 0xa4, 0x5c, 0xcc, 0x5d, 0x65, 0xb6, 0x92,
            0x6c, 0x70, 0x48, 0x50, 0xfd, 0xed, 0xb9, 0xda, 0x5e, 0x15, 0x46, 0x57, 0xa7, 0x8d, 0x9d, 0x84,
            0x90, 0xd8, 0xab, 0x00, 0x8c, 0xbc, 0xd3, 0x0a, 0xf7, 0xe4, 0x58, 0x05, 0xb8, 0xb3, 0x45, 0x06,
            0xd0, 0x2c, 0x1e, 0x8f, 0xca, 0x3f, 0x0f, 0x02, 0xc1, 0xaf, 0xbd, 0x03, 0x01, 0x13, 0x8a, 0x6b,
            0x3a, 0x91, 0x11, 0x41, 0x4f, 0x67, 0xdc, 0xea, 0x97, 0xf2, 0xcf, 0xce, 0xf0, 0xb4, 0xe6, 0x73,
            0x96, 0xac, 0x74, 0x22, 0xe7, 0xad, 0x35, 0x85, 0xe2, 0xf9, 0x37, 0xe8, 0x1c, 0x75, 0xdf, 0x6e,
            0x47, 0xf1, 0x1a, 0x71, 0x1d, 0x29, 0xc5, 0x89, 0x6f, 0xb7, 0x62, 0x0e, 0xaa, 0x18, 0xbe, 0x1b,
            0xfc, 0x56, 0x3e, 0x4b, 0xc6, 0xd2, 0x79, 0x20, 0x9a, 0xdb, 0xc0, 0xfe, 0x78, 0xcd, 0x5a, 0xf4,
            0x1f, 0xdd, 0xa8, 0x33, 0x88, 0x07, 0xc7, 0x31, 0xb1, 0x12, 0x10, 0x59, 0x27, 0x80, 0xec, 0x5f,
            0x60, 0x51, 0x7f, 0xa9, 0x19, 0xb5, 0x4a, 0x0d, 0x2d, 0xe5, 0x7a, 0x9f, 0x93, 0xc9, 0x9c, 0xef,
            0xa0, 0xe0, 0x3b, 0x4d, 0xae, 0x2a, 0xf5, 0xb0, 0xc8, 0xeb, 0xbb, 0x3c, 0x83, 0x53, 0x99, 0x61,
            0x17, 0x2b, 0x04, 0x7e, 0xba, 0x77, 0xd6, 0x26, 0xe1, 0x69, 0x14, 0x63, 0x55, 0x21, 0x0c, 0x7d)
MIX_COLUMN_MATRIX = ((0x2, 0x3, 0x1, 0x1),
                     (0x1, 0x2, 0x3, 0x1),
                     (0x1, 0x1, 0x2, 0x3),
                     (0x3, 0x1, 0x1, 0x2))
MIX_COLUMN_MATRIX_INV = ((0xE, 0xB, 0xD, 0x9),
                         (0x9, 0xE, 0xB, 0xD),
                         (0xD, 0x9, 0xE, 0xB),
                         (0xB, 0xD, 0x9, 0xE))
RIJNDAEL_EXP_TABLE = (0x01, 0x03, 0x05, 0x0F, 0x11, 0x33, 0x55, 0xFF, 0x1A, 0x2E, 0x72, 0x96, 0xA1, 0xF8, 0x13, 0x35,
                      0x5F, 0xE1, 0x38, 0x48, 0xD8, 0x73, 0x95, 0xA4, 0xF7, 0x02, 0x06, 0x0A, 0x1E, 0x22, 0x66, 0xAA,
                      0xE5, 0x34, 0x5C, 0xE4, 0x37, 0x59, 0xEB, 0x26, 0x6A, 0xBE, 0xD9, 0x70, 0x90, 0xAB, 0xE6, 0x31,
                      0x53, 0xF5, 0x04, 0x0C, 0x14, 0x3C, 0x44, 0xCC, 0x4F, 0xD1, 0x68, 0xB8, 0xD3, 0x6E, 0xB2, 0xCD,
                      0x4C, 0xD4, 0x67, 0xA9, 0xE0, 0x3B, 0x4D, 0xD7, 0x62, 0xA6, 0xF1, 0x08, 0x18, 0x28, 0x78, 0x88,
                      0x83, 0x9E, 0xB9, 0xD0, 0x6B, 0xBD, 0xDC, 0x7F, 0x81, 0x98, 0xB3, 0xCE, 0x49, 0xDB, 0x76, 0x9A,
                      0xB5, 0xC4, 0x57, 0xF9, 0x10, 0x30, 0x50, 0xF0, 0x0B, 0x1D, 0x27, 0x69, 0xBB, 0xD6, 0x61, 0xA3,
                      0xFE, 0x19, 0x2B, 0x7D, 0x87, 0x92, 0xAD, 0xEC, 0x2F, 0x71, 0x93, 0xAE, 0xE9, 0x20, 0x60, 0xA0,
                      0xFB, 0x16, 0x3A, 0x4E, 0xD2, 0x6D, 0xB7, 0xC2, 0x5D, 0xE7, 0x32, 0x56, 0xFA, 0x15, 0x3F, 0x41,
                      0xC3, 0x5E, 0xE2, 0x3D, 0x47, 0xC9, 0x40, 0xC0, 0x5B, 0xED, 0x2C, 0x74, 0x9C, 0xBF, 0xDA, 0x75,
                      0x9F, 0xBA, 0xD5, 0x64, 0xAC, 0xEF, 0x2A, 0x7E, 0x82, 0x9D, 0xBC, 0xDF, 0x7A, 0x8E, 0x89, 0x80,
                      0x9B, 0xB6, 0xC1, 0x58, 0xE8, 0x23, 0x65, 0xAF, 0xEA, 0x25, 0x6F, 0xB1, 0xC8, 0x43, 0xC5, 0x54,
                      0xFC, 0x1F, 0x21, 0x63, 0xA5, 0xF4, 0x07, 0x09, 0x1B, 0x2D, 0x77, 0x99, 0xB0, 0xCB, 0x46, 0xCA,
                      0x45, 0xCF, 0x4A, 0xDE, 0x79, 0x8B, 0x86, 0x91, 0xA8, 0xE3, 0x3E, 0x42, 0xC6, 0x51, 0xF3, 0x0E,
                      0x12, 0x36, 0x5A, 0xEE, 0x29, 0x7B, 0x8D, 0x8C, 0x8F, 0x8A, 0x85, 0x94, 0xA7, 0xF2, 0x0D, 0x17,
                      0x39, 0x4B, 0xDD, 0x7C, 0x84, 0x97, 0xA2, 0xFD, 0x1C, 0x24, 0x6C, 0xB4, 0xC7, 0x52, 0xF6, 0x01)
RIJNDAEL_LOG_TABLE = (0x00, 0x00, 0x19, 0x01, 0x32, 0x02, 0x1a, 0xc6, 0x4b, 0xc7, 0x1b, 0x68, 0x33, 0xee, 0xdf, 0x03,
                      0x64, 0x04, 0xe0, 0x0e, 0x34, 0x8d, 0x81, 0xef, 0x4c, 0x71, 0x08, 0xc8, 0xf8, 0x69, 0x1c, 0xc1,
                      0x7d, 0xc2, 0x1d, 0xb5, 0xf9, 0xb9, 0x27, 0x6a, 0x4d, 0xe4, 0xa6, 0x72, 0x9a, 0xc9, 0x09, 0x78,
                      0x65, 0x2f, 0x8a, 0x05, 0x21, 0x0f, 0xe1, 0x24, 0x12, 0xf0, 0x82, 0x45, 0x35, 0x93, 0xda, 0x8e,
                      0x96, 0x8f, 0xdb, 0xbd, 0x36, 0xd0, 0xce, 0x94, 0x13, 0x5c, 0xd2, 0xf1, 0x40, 0x46, 0x83, 0x38,
                      0x66, 0xdd, 0xfd, 0x30, 0xbf, 0x06, 0x8b, 0x62, 0xb3, 0x25, 0xe2, 0x98, 0x22, 0x88, 0x91, 0x10,
                      0x7e, 0x6e, 0x48, 0xc3, 0xa3, 0xb6, 0x1e, 0x42, 0x3a, 0x6b, 0x28, 0x54, 0xfa, 0x85, 0x3d, 0xba,
                      0x2b, 0x79, 0x0a, 0x15, 0x9b, 0x9f, 0x5e, 0xca, 0x4e, 0xd4, 0xac, 0xe5, 0xf3, 0x73, 0xa7, 0x57,
                      0xaf, 0x58, 0xa8, 0x50, 0xf4, 0xea, 0xd6, 0x74, 0x4f, 0xae, 0xe9, 0xd5, 0xe7, 0xe6, 0xad, 0xe8,
                      0x2c, 0xd7, 0x75, 0x7a, 0xeb, 0x16, 0x0b, 0xf5, 0x59, 0xcb, 0x5f, 0xb0, 0x9c, 0xa9, 0x51, 0xa0,
                      0x7f, 0x0c, 0xf6, 0x6f, 0x17, 0xc4, 0x49, 0xec, 0xd8, 0x43, 0x1f, 0x2d, 0xa4, 0x76, 0x7b, 0xb7,
                      0xcc, 0xbb, 0x3e, 0x5a, 0xfb, 0x60, 0xb1, 0x86, 0x3b, 0x52, 0xa1, 0x6c, 0xaa, 0x55, 0x29, 0x9d,
                      0x97, 0xb2, 0x87, 0x90, 0x61, 0xbe, 0xdc, 0xfc, 0xbc, 0x95, 0xcf, 0xcd, 0x37, 0x3f, 0x5b, 0xd1,
                      0x53, 0x39, 0x84, 0x3c, 0x41, 0xa2, 0x6d, 0x47, 0x14, 0x2a, 0x9e, 0x5d, 0x56, 0xf2, 0xd3, 0xab,
                      0x44, 0x11, 0x92, 0xd9, 0x23, 0x20, 0x2e, 0x89, 0xb4, 0x7c, 0xb8, 0x26, 0x77, 0x99, 0xe3, 0xa5,
                      0x67, 0x4a, 0xed, 0xde, 0xc5, 0x31, 0xfe, 0x18, 0x0d, 0x63, 0x8c, 0x80, 0xc0, 0xf7, 0x70, 0x07)


def key_expansion(data):
    """
    Generate key schedule

    @param {int[]} data  16/24/32-Byte cipher key
    @returns {int[]}     176/208/240-Byte expanded key
    """
    data = data[:]  # copy
    rcon_iteration = 1
    key_size_bytes = len(data)
    expanded_key_size_bytes = (key_size_bytes // 4 + 7) * BLOCK_SIZE_BYTES

    while len(data) < expanded_key_size_bytes:
        temp = data[-4:]
        temp = key_schedule_core(temp, rcon_iteration)
        rcon_iteration += 1
        data += xor(temp, data[-key_size_bytes: 4 - key_size_bytes])

        for _ in range(3):
            temp = data[-4:]
            data += xor(temp, data[-key_size_bytes: 4 - key_size_bytes])

        if key_size_bytes == 32:
            temp = data[-4:]
            temp = sub_bytes(temp)
            data += xor(temp, data[-key_size_bytes: 4 - key_size_bytes])

        for _ in range(3 if key_size_bytes == 32 else 2 if key_size_bytes == 24 else 0):
            temp = data[-4:]
            data += xor(temp, data[-key_size_bytes: 4 - key_size_bytes])
    return data[:expanded_key_size_bytes]


def iter_vector(iv):
    while True:
        yield iv
        iv = inc(iv)


def sub_bytes(data):
    return [SBOX[x] for x in data]


def sub_bytes_inv(data):
    return [SBOX_INV[x] for x in data]


def rotate(data):
    return data[1:] + [data[0]]


def key_schedule_core(data, rcon_iteration):
    data = rotate(data)
    data = sub_bytes(data)
    data[0] = data[0] ^ RCON[rcon_iteration]

    return data


def xor(data1, data2):
    return [x ^ y for x, y in zip(data1, data2)]


def iter_mix_columns(data, matrix):
    for i in (0, 4, 8, 12):
        for row in matrix:
            mixed = 0
            for j in range(4):
                # xor is (+) and (-)
                mixed ^= (0 if data[i:i + 4][j] == 0 or row[j] == 0 else
                          RIJNDAEL_EXP_TABLE[(RIJNDAEL_LOG_TABLE[data[i + j]] + RIJNDAEL_LOG_TABLE[row[j]]) % 0xFF])
            yield mixed


def shift_rows(data):
    return [data[((column + row) & 0b11) * 4 + row] for column in range(4) for row in range(4)]


def shift_rows_inv(data):
    return [data[((column - row) & 0b11) * 4 + row] for column in range(4) for row in range(4)]


def shift_block(data):
    data_shifted = []

    bit = 0
    for n in data:
        if bit:
            n |= 0x100
        bit = n & 1
        n >>= 1
        data_shifted.append(n)

    return data_shifted


def inc(data):
    data = data[:]  # copy
    for i in range(len(data) - 1, -1, -1):
        if data[i] == 255:
            data[i] = 0
        else:
            data[i] = data[i] + 1
            break
    return data


def block_product(block_x, block_y):
    # NIST SP 800-38D, Algorithm 1

    if len(block_x) != BLOCK_SIZE_BYTES or len(block_y) != BLOCK_SIZE_BYTES:
        raise ValueError(f'Length of blocks need to be {BLOCK_SIZE_BYTES} bytes')

    block_r = [0xE1] + [0] * (BLOCK_SIZE_BYTES - 1)
    block_v = block_y[:]
    block_z = [0] * BLOCK_SIZE_BYTES

    for i in block_x:
        for bit in range(7, -1, -1):
            if i & (1 << bit):
                block_z = xor(block_z, block_v)

            do_xor = block_v[-1] & 1
            block_v = shift_block(block_v)
            if do_xor:
                block_v = xor(block_v, block_r)

    return block_z


def ghash(subkey, data):
    # NIST SP 800-38D, Algorithm 2

    if len(data) % BLOCK_SIZE_BYTES:
        raise ValueError(f'Length of data should be {BLOCK_SIZE_BYTES} bytes')

    last_y = [0] * BLOCK_SIZE_BYTES
    for i in range(0, len(data), BLOCK_SIZE_BYTES):
        block = data[i: i + BLOCK_SIZE_BYTES]
        last_y = block_product(xor(last_y, block), subkey)

    return last_y


__all__ = [
    'aes_cbc_decrypt',
    'aes_cbc_decrypt_bytes',
    'aes_ctr_decrypt',
    'aes_decrypt_text',
    'aes_decrypt',
    'aes_ecb_decrypt',
    'aes_gcm_decrypt_and_verify',
    'aes_gcm_decrypt_and_verify_bytes',

    'aes_cbc_encrypt',
    'aes_cbc_encrypt_bytes',
    'aes_ctr_encrypt',
    'aes_ecb_encrypt',
    'aes_encrypt',

    'key_expansion',
    'pad_block',
    'pkcs7_padding',
    'unpad_pkcs7',
]
