{
  description = "Pinned experimental OnePlus 9 Pro ColorOS kernel (not device validation)";
  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-26.05";
  outputs = { self, nixpkgs }:
    let
      system = "x86_64-linux";
      pkgs = import nixpkgs { inherit system; };
      kernel = pkgs.callPackage ./nix/kernel.nix { project = self; };
      pipeline = pkgs.callPackage ./nix/packaging.nix { project = self; };
    in {
      packages.${system} = {
        coloros-kernel = kernel;
        coloros-pipeline = pipeline;
      };
      apps.${system}.coloros-pipeline = {
        type = "app";
        program = pkgs.lib.getExe pipeline;
        meta.description = "Qualify and package a locked OnePlus 9 Pro ColorOS kernel";
      };
      devShells.${system}.default = pkgs.mkShell {
        inputsFrom = [ kernel ];
        packages = [ pkgs.nix pkgs.git pkgs.python3 pkgs.actionlint ];
        shellHook = ''
          echo 'ColorOS kernel: nix build --option sandbox true --option sandbox-fallback false .#coloros-kernel'
          echo 'Development shell is not an offline sandbox; production build is a derivation.'
        '';
      };
    };
}
