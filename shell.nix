{ pkgs ? import<nixpkgs> {} }:
pkgs.mkShell {
	buildInputs = import pkgs; [ 
    uv 
    pyright
  ];
}
