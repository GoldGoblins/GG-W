<?php
$root = $_SERVER["DOCUMENT_ROOT"] ?? "";
$path = parse_url($_SERVER["REQUEST_URI"] ?? "/", PHP_URL_PATH);
$path = is_string($path) ? $path : "/";
$file = $root . $path;
if ($path !== "/" && is_file($file)) {
    return false;
}
$index = $root . "/index.php";
if (is_file($index)) {
    require $index;
    return true;
}
return false;
