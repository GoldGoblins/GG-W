// SPDX-License-Identifier: MIT
pragma solidity 0.8.38;

import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";

/// @notice Disposable GG test token. No mainnet GGHB identity or economic value.
/// @dev One fixed allocation; no administrator, further minting, tax or upgrade.
contract GGTestToken is ERC20 {
    constructor() ERC20("GG Test Token", "GG-TEST") {
        _mint(msg.sender, 1_000_000 * 10 ** decimals());
    }

    function decimals() public pure override returns (uint8) {
        return 6;
    }
}
