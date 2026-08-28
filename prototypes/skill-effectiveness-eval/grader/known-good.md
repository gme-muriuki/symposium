# cargo-platform 0.3.3 API notes

Platform variants: `Name(String)`, `Cfg(CfgExpr)`
Cfg variants: `Name(Ident)`, `KeyPair(Ident, String)`
Platform::matches parameters after self: `name: &str`, `cfg: &[Cfg]`
