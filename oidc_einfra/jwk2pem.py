import jwcrypto.jwk

key_dict = {
    "e": "AQAB",
    "kty": "RSA",
    "n": "mho5h_lz6USUUazQaVT3PHloIk_Ljs2vZl_RAaitkXDx6aqpl1kGpS44eYJOaer4oWc6_QNaMtynvlSlnkuWrG765adNKT9sgAWSrPb81xkojsQabrSNv4nIOWUQi0Tjh0WxXQmbV-bMxkVaElhdHNFzUfHv-XqI8Hkc82mIGtyeMQn-VAuZbYkVXnjyCwwa9RmPOSH-O4N4epDXKk1VK9dUxf_rEYbjMNZGDva30do0mrBkU8W3O1mDVJSSgHn4ejKdGNYMm0JKPAgCWyPWJDoL092ctPCFlUMBBZ_OP3omvgnw0GaWZXxqSqaSvxFJkqCHqLMwpxmWTTAgEvAbnw",
}

key = jwcrypto.jwk.JWK(**key_dict)
pem = key.export_to_pem(False, False)
print(pem)
