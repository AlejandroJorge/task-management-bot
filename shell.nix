{ pkgs ? import<nixpkgs> {} }:
pkgs.mkShell {
	buildInputs = [ 
    pkgs.uv 
    pkgs.pyright
  ];
}
