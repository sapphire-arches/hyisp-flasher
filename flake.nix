{
  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs";
  };

  outputs = {self, nixpkgs}: {
    devShells.x86_64-linux.default =
      let
        pkgs = import nixpkgs { system = "x86_64-linux"; };
        python = pkgs.python312.withPackages (pyPkgs: [
          pyPkgs.libusb1
        ]);
      in
        pkgs.mkShell {
          name = "fwupdater-devel";

          buildInputs = [
            python
          ];
        };
  };
}
