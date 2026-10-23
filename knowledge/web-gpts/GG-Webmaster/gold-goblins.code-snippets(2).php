<?php

/**
 * Gold Goblins Custom Product Layout
 */
add_shortcode('goblin_product', function($atts) {
    if (!class_exists('WooCommerce')) {
        return '<p>WooCommerce är inte aktivt.</p>';
    }

    $atts = shortcode_atts([
        'id' => get_the_ID(),
    ], $atts);

    $product_id = intval($atts['id']);
    $product = wc_get_product($product_id);

    if (!$product) {
        return '<p>Produkten hittades inte.</p>';
    }

    global $post;
    $old_post = $post;
    $post = get_post($product_id);
    setup_postdata($post);

    if ($product && $product->is_type('variable')) {
        wp_enqueue_script('wc-add-to-cart-variation');
    }

    $gg_variation_prices = [];

    if ($product && $product->is_type('variable')) {
        foreach ($product->get_available_variations() as $variation) {
            if (empty($variation['attributes']) || empty($variation['price_html'])) {
                continue;
            }

            foreach ($variation['attributes'] as $attr_name => $attr_value) {
                if (!empty($attr_value)) {
                    $gg_variation_prices[$attr_value] = $variation['price_html'];
                }
            }
        }
    }

    ob_start();
    ?>

<div id="gg-product-detail" class="gg-product-wrapper">

    <section id="gg-product-inner" class="gg-product-section">

        <div class="gg-product-gallery">
            <?php
            $main_image_id = $product->get_image_id();
            $gallery_ids = $product->get_gallery_image_ids();

            if ($main_image_id) {
                echo wp_get_attachment_image($main_image_id, 'large', false, [
                    'class' => 'gg-main-image',
                    'id' => 'gg-main-product-image'
                ]);
            }

            if (!empty($gallery_ids) || $main_image_id) :
                $all_images = array_merge([$main_image_id], $gallery_ids);
                ?>
                <div class="gg-thumbnails">
                    <?php foreach ($all_images as $image_id) :
                        $thumb = wp_get_attachment_image_url($image_id, 'thumbnail');
                        $large = wp_get_attachment_image_url($image_id, 'large');
                        ?>
                        <img class="gg-thumb" src="<?php echo esc_url($thumb); ?>" data-large="<?php echo esc_url($large); ?>" alt="">
                    <?php endforeach; ?>
                </div>
            <?php endif; ?>
        </div>

        <div class="gg-product-info">
            <p class="gg-kicker">Gold Goblins Collection</p>
            <h1><?php echo esc_html($product->get_name()); ?></h1>

            <div class="gg-price">
                <?php echo wp_kses_post($product->get_price_html()); ?>
            </div>

            <div class="gg-short-description">
                <?php echo wp_kses_post($product->get_short_description()); ?>
            </div>

            <div class="gg-stock-status">
                <?php echo wc_get_stock_html($product); ?>
            </div>

            <div class="gg-cart-form">
                <?php woocommerce_template_single_add_to_cart(); ?>
            </div>
        </div>

    </section>
</div>

<style>
.gg-product-wrapper{
    width:100%;
    min-height:unset;
    padding:clamp(0.8rem, 2vw, 1.5rem) 0 clamp(1.5rem, 3vw, 2.5rem);
    position:relative;
    z-index:2;
    background-color:#f1dfc4;
    background-image:
        radial-gradient(circle at 20% 15%, rgba(255,255,255,0.10), transparent 30%),
        radial-gradient(circle at 80% 35%, rgba(120,90,55,0.03), transparent 35%),
        radial-gradient(circle at 45% 80%, rgba(255,255,255,0.06), transparent 30%),
        linear-gradient(135deg, rgba(255,255,255,0.03), rgba(120,90,55,0.02));
    background-size:cover;
    background-position:center;
}

	.gg-product-wrapper::before{
    content:"";
    position:absolute;
    left:0;
    right:0;
    top:0;

    height:1px;

    background:linear-gradient(
        90deg,
        transparent 0%,
        rgba(159,133,96,0.28) 18%,
        rgba(159,133,96,0.70) 50%,
        rgba(159,133,96,0.28) 82%,
        transparent 100%
    );

    pointer-events:none;
}
	
.gg-product-section{
    display:grid;
    grid-template-columns:minmax(0, 1.08fr) minmax(0, 0.92fr);
    gap:clamp(1.2rem, 3vw, 3rem);
    width:min(82vw, 62rem);
    margin:0 auto;
    padding:0;
}

.gg-main-image{
    width:100%;
    height:52vh;
    max-height:32rem;
    object-fit:cover;
    display:block;
}

.gg-thumbnails{
    display:grid;
    grid-template-columns:repeat(5, 1fr);
    gap:clamp(0.35rem, 0.8vw, 0.7rem);
    margin-top:clamp(0.4rem, 0.8vw, 0.7rem);
}

.gg-thumb{
    width:100%;
    aspect-ratio:1 / 1;
    object-fit:cover;
    cursor:pointer;
    border:1px solid transparent;
    transition:all 0.2s ease;
}

.gg-thumb:hover{
    opacity:0.85;
    border-color:#B9965F;
    transform:scale(1.02);
}

.gg-product-info{
    min-height:52vh;
    display:flex;
    flex-direction:column;
    gap:clamp(10px, 1vw, 20px);
}

.gg-kicker{
    color:#B9965F;
    text-transform:uppercase;
    font-weight:500;
    font-size:clamp(0.55rem, 0.75vw, 0.75rem);
    letter-spacing:clamp(0.08rem, 0.18vw, 0.14rem);
    margin:0;
}

.gg-product-info h1{
    color:#111;
    font-size:1.8vw;
    letter-spacing:clamp(0.08rem, 0.14vw, 0.14rem);
    font-family:'PT Serif', serif;
    line-height:1;
    font-weight:400;
    margin:0;
}

.gg-price{
    font-family:'PT Serif', serif;
    font-size:clamp(18px, 1.45vw, 24px);
    line-height:1.4;
    margin:0;
}

.gg-short-description{
    font-family:'PT Serif', serif;
    font-size:clamp(12px, 1vw, 16px);
    line-height:1.65;
    margin:0;
}

.gg-stock-status .stock{
    color:#B9965F;
    font-family:'PT Serif', serif;
    font-size:0.85rem;
    letter-spacing:0.08em;
    margin:0;
    text-transform:uppercase;
}

.gg-cart-form{
    margin-top:0;
}

.gg-cart-form form.cart{
    width:100%;
}

.gg-cart-form .stock{
    display:none !important;
}

.gg-cart-form table.variations{
    width:100%;
    margin:0 0 12px;
    border:0;
}

.gg-cart-form table.variations tbody,
.gg-cart-form table.variations tr,
.gg-cart-form table.variations th,
.gg-cart-form table.variations td{
    display:block;
    width:100%;
    padding:0;
    border:0;
}

.gg-cart-form table.variations label{
    color:#B9965F;
    font-family:'PT Serif', serif;
    font-size:12px;
    letter-spacing:0.16em;
    text-transform:uppercase;
    text-align:center;
    font-weight:400;
}

.gg-cart-form table.variations select{
    width:100%;
    margin-bottom:10px;
    padding:10px 12px;
    border:1px solid #b8a98f;
    background:#f1dfc4;
    color:#2f2b25;
    font-family:'PT Serif', serif;
    font-size:15px;
}

.gg-cart-form table.variations select option{
    background:#f1dfc4;
    color:#2f2b25;
}

.gg-cart-form .reset_variations{
    color:#B9965F !important;
    font-family:'PT Serif', serif;
    font-size:12px;
    text-decoration:none;
    border-bottom:1px solid #B9965F;
    margin-left:8px;
}

.gg-cart-form .reset_variations:hover{
    opacity:0.75;
}

.gg-cart-form .woocommerce-variation-price{
    display:none !important;
}

.gg-cart-form .single_variation_wrap{
    width:100%;
}

.gg-cart-form .woocommerce-variation-add-to-cart{
    display:block;
    width:100%;
}

.gg-cart-form .quantity{
    display:flex;
    align-items:center;
    justify-content:center;
    gap:32px;
    width:100%;
    border:0;
    margin-bottom:6px;
}

.gg-cart-form .quantity input.qty{
    border:0;
    text-align:center;
    background:transparent;
    width:30px;
    padding:10px 0;
    margin:0;
    font-family:'PT Serif', serif;
    font-size:16px;
    color:#111;
}

.gg-cart-form input.qty::-webkit-outer-spin-button,
.gg-cart-form input.qty::-webkit-inner-spin-button{
    -webkit-appearance:none;
    margin:0;
}

.gg-cart-form input.qty{
    -moz-appearance:textfield;
    appearance:textfield;
}

.gg-qty-btn{
    flex:none;
    width:24px;
    background:transparent;
    border:0;
    color:#2f2b25;
    cursor:pointer;
    font-size:20px;
    line-height:1;
    padding:10px;
    font-family:'PT Serif', serif;
}

.gg-qty-btn:hover{
    color:#B9965F;
}

.gg-cart-form .single_add_to_cart_button{
    width:100%;
    display:inline-flex;
    justify-content:center;
    align-items:center;
    padding:10px 18px;
    margin-top:0;
    border:2px solid #aa8a58;
    color:#3a2c1f;
    text-decoration:none;
    font-family:Georgia, "Times New Roman", serif;
    font-size:clamp(12px, 0.8vw, 15px);
    text-transform:uppercase;
    letter-spacing:0.08em;
    cursor:pointer;
    background-color:#f1dfc4;
    background-image:
        radial-gradient(circle at 20% 15%, rgba(255,255,255,0.10), transparent 30%),
        radial-gradient(circle at 80% 35%, rgba(120,90,55,0.03), transparent 35%),
        radial-gradient(circle at 45% 80%, rgba(255,255,255,0.06), transparent 30%),
        linear-gradient(135deg, rgba(255,255,255,0.03), rgba(120,90,55,0.02));
    background-size:cover;
    background-position:center;
    transition:all 0.25s ease;
}

.gg-cart-form .single_add_to_cart_button:hover{
    transform:translateY(-1px);
    border-color:#c4a26d;
    box-shadow:0 4px 12px rgba(0,0,0,0.08);
}

.gg-cart-form .single_add_to_cart_button:focus,
.gg-cart-form .single_add_to_cart_button:active{
    outline:none;
}

@media(max-width:800px){
    .gg-product-section{
        grid-template-columns:1fr;
    }

    .gg-product-info{
        height:auto;
        max-height:none;
    }

    .gg-product-info h1{
        font-size:clamp(2rem, 9vw, 3rem);
    }
}
</style>

<script>
document.addEventListener('click', function(e) {
    if (!e.target.classList.contains('gg-thumb')) return;

    const mainImg = document.getElementById('gg-main-product-image');
    const newSrc = e.target.getAttribute('data-large');

    if (mainImg && newSrc) {
        mainImg.src = newSrc;
        mainImg.srcset = '';
    }
});

const ggVariationPrices = <?php echo wp_json_encode($gg_variation_prices); ?>;

document.addEventListener('change', function(e) {
    if (!e.target.matches('.gg-cart-form select')) return;

    const priceBox = document.querySelector('#gg-product-detail .gg-price');

    if (!priceBox) return;

    if (!priceBox.dataset.originalPrice) {
        priceBox.dataset.originalPrice = priceBox.innerHTML;
    }

    const selectedValue = e.target.value;

    if (selectedValue && ggVariationPrices && ggVariationPrices[selectedValue]) {
        priceBox.innerHTML = ggVariationPrices[selectedValue];
    } else {
        priceBox.innerHTML = priceBox.dataset.originalPrice;
    }
});

document.addEventListener('click', function(e) {
    if (!e.target.matches('.reset_variations')) return;

    const priceBox = document.querySelector('#gg-product-detail .gg-price');

    if (priceBox && priceBox.dataset.originalPrice) {
        setTimeout(function() {
            priceBox.innerHTML = priceBox.dataset.originalPrice;
        }, 50);
    }
});

document.addEventListener('submit', function(e) {
    const form = e.target;

    if (!form.classList.contains('cart')) return;

    e.preventDefault();

    const button = form.querySelector('.single_add_to_cart_button');
    const formData = new FormData(form);

    let variationId = formData.get('variation_id');

    if (form.classList.contains('variations_form') && (!variationId || variationId === '0')) {
        const selectedSize = form.querySelector('select[name^="attribute_"]')?.value;
        const variations = JSON.parse(form.getAttribute('data-product_variations') || '[]');

        const match = variations.find(function(v) {
            return Object.values(v.attributes).includes(selectedSize);
        });

        if (match && match.variation_id) {
            variationId = match.variation_id;
            formData.set('variation_id', variationId);
        }
    }

    if (form.classList.contains('variations_form') && (!variationId || variationId === '0')) {
        alert('Välj storlek först.');
        return;
    }

    const productId =
        formData.get('product_id') ||
        formData.get('add-to-cart') ||
        form.querySelector('[name="product_id"]')?.value ||
        button?.value;

   if (form.classList.contains('variations_form')) {
    formData.set('product_id', productId);

    if (variationId) {
        formData.set('variation_id', variationId);
        formData.set('add-to-cart', productId);
    }
} else {
    formData.set('add-to-cart', productId);
}

    if (button) {
        button.disabled = true;
        button.textContent = 'Lägger till...';
    }

    fetch(window.location.href, {
        method: 'POST',
        body: formData,
        credentials: 'same-origin'
    })
    .then(function() {
        document.body.dispatchEvent(new Event('wc_fragment_refresh'));

        if (typeof ggLoadSideCart === 'function') {
            ggLoadSideCart();
        }

        const cart = document.getElementById('gg-side-cart');
        const overlay = document.getElementById('gg-cart-overlay');

        if (cart && overlay) {
            cart.classList.add('open');
            overlay.classList.add('open');
        }

        if (button) {
            button.disabled = false;
            button.textContent = 'Tillagd i varukorg';
        }

        setTimeout(function() {
            if (button) {
                button.textContent = 'Lägg i varukorg';
            }
        }, 1800);
    })
    .catch(function() {
        if (button) {
            button.disabled = false;
            button.textContent = 'Försök igen';
        }
    });
});

document.addEventListener('click', function(e) {
    if (e.target.classList.contains('gg-qty-minus')) {
        const qty = e.target.parentNode.querySelector('input.qty');
        qty.stepDown();
        qty.dispatchEvent(new Event('change'));
    }

    if (e.target.classList.contains('gg-qty-plus')) {
        const qty = e.target.parentNode.querySelector('input.qty');
        qty.stepUp();
        qty.dispatchEvent(new Event('change'));
    }
});
</script>

    <?php

    wp_reset_postdata();
    $post = $old_post;

    return ob_get_clean();
});

add_action('woocommerce_before_quantity_input_field', function(){
    global $product;

    if ($product && $product->is_sold_individually()) {
        return;
    }

    echo '<button type="button" class="gg-qty-btn gg-qty-minus">−</button>';
});

add_action('woocommerce_after_quantity_input_field', function(){
    global $product;

    if ($product && $product->is_sold_individually()) {
        return;
    }

    echo '<button type="button" class="gg-qty-btn gg-qty-plus">+</button>';
});

add_action('wp_ajax_gg_load_product', 'gg_load_product_ajax');
add_action('wp_ajax_nopriv_gg_load_product', 'gg_load_product_ajax');

add_filter('woocommerce_product_single_add_to_cart_text', function($text) {
    return 'Lägg i varukorg';
});

add_filter('woocommerce_product_add_to_cart_text', function($text) {
    return 'Lägg i varukorg';
});

add_filter('woocommerce_add_to_cart_form_action', function($url) {
    return '';
});

add_filter('woocommerce_dropdown_variation_attribute_options_args', function($args) {
    $args['show_option_none'] = 'Välj storlek';
    return $args;
});

add_filter('gettext', function($translated, $text, $domain) {
    if ($text === 'Clear') {
        return 'Rensa';
    }

    if ($text === 'Choose an option') {
        return 'Välj storlek';
    }

    return $translated;
}, 20, 3);

add_action('wp_ajax_gg_get_side_cart', 'gg_get_side_cart');
add_action('wp_ajax_nopriv_gg_get_side_cart', 'gg_get_side_cart');

function gg_get_side_cart() {
    if (!class_exists('WooCommerce')) {
        wp_die();
    }

    ob_start();

    if (WC()->cart && !WC()->cart->is_empty()) {
        foreach (WC()->cart->get_cart() as $cart_item_key => $cart_item) {
            $product = $cart_item['data'];

            if (!$product) {
                continue;
            }

            $thumb = $product->get_image('thumbnail');

            echo '<div class="gg-side-cart-item">';
            echo '<div class="gg-side-cart-thumb">' . $thumb . '</div>';

            echo '<div class="gg-side-cart-info">';
            echo '<div class="gg-side-cart-item-title">' . esc_html($product->get_name()) . '</div>';
            echo '<div class="gg-side-cart-item-meta">';

            $quantity = intval($cart_item['quantity']);
            $stock_quantity = $product->get_stock_quantity();

            $can_change_qty = true;

            if ($product->managing_stock() && $stock_quantity !== null && $stock_quantity <= 1) {
                $can_change_qty = false;
            }

            if ($product->is_sold_individually()) {
                $can_change_qty = false;
            }

            if ($can_change_qty) {
                echo '<div class="gg-side-cart-qty">';
                echo '<button class="gg-cart-qty-minus" data-cart-key="' . esc_attr($cart_item_key) . '" type="button">−</button>';
                echo '<span>' . esc_html($quantity) . '</span>';
                echo '<button class="gg-cart-qty-plus" data-cart-key="' . esc_attr($cart_item_key) . '" type="button">+</button>';
                echo '</div>';
            } else {
                echo '<div class="gg-side-cart-qty-static">';
                echo '<span>Antal: ' . esc_html($quantity) . '</span>';
                echo '</div>';
            }

            echo '<div class="gg-side-cart-price">';
            echo wp_kses_post(wc_price($product->get_price()));
            echo '</div>';

            echo '</div>';
            echo '</div>';

            echo '<button class="gg-side-cart-remove" data-cart-key="' . esc_attr($cart_item_key) . '" type="button">×</button>';
            echo '</div>';
        }

        echo '<div class="gg-side-cart-total">';
        echo '<span>Totalt</span>';
        echo '<strong>' . wp_kses_post(WC()->cart->get_cart_total()) . '</strong>';
        echo '</div>';
    } else {
        echo '<p>Din varukorg är tom.</p>';
    }

    echo ob_get_clean();
    wp_die();
}

add_action('wp_ajax_gg_get_cart_count', 'gg_get_cart_count');
add_action('wp_ajax_nopriv_gg_get_cart_count', 'gg_get_cart_count');

function gg_get_cart_count() {
    if (!class_exists('WooCommerce') || !WC()->cart) {
        echo 0;
        wp_die();
    }

    echo WC()->cart->get_cart_contents_count();
    wp_die();
}

function gg_load_product_ajax() {
    if (!isset($_POST['product_id'])) {
        wp_die('Produkt-ID saknas.');
    }

    $product_id = intval($_POST['product_id']);

    echo do_shortcode('[goblin_product id="' . $product_id . '"]');

    wp_die();
}

add_action('wp_ajax_gg_remove_cart_item', 'gg_remove_cart_item');
add_action('wp_ajax_nopriv_gg_remove_cart_item', 'gg_remove_cart_item');

function gg_remove_cart_item() {
    if (!class_exists('WooCommerce') || !WC()->cart || !isset($_POST['cart_key'])) {
        wp_die();
    }

    WC()->cart->remove_cart_item(sanitize_text_field($_POST['cart_key']));

    wp_die();
}



add_action('wp_ajax_gg_update_cart_qty', 'gg_update_cart_qty');
add_action('wp_ajax_nopriv_gg_update_cart_qty', 'gg_update_cart_qty');

function gg_update_cart_qty() {
    if (!class_exists('WooCommerce') || !WC()->cart || !isset($_POST['cart_key']) || !isset($_POST['change'])) {
        wp_die();
    }

    $cart_key = sanitize_text_field($_POST['cart_key']);
    $change = intval($_POST['change']);

    $cart = WC()->cart->get_cart();

    if (!isset($cart[$cart_key])) {
        wp_die();
    }

    $current_qty = intval($cart[$cart_key]['quantity']);
    $new_qty = max(0, $current_qty + $change);

    WC()->cart->set_quantity($cart_key, $new_qty, true);

    wp_die();
}

/**
 * Gold Goblins Product Extra Section
 */
add_shortcode('goblin_product_extra', function($atts) {
    if (!class_exists('WooCommerce')) {
        return '<p>WooCommerce är inte aktivt.</p>';
    }

    $atts = shortcode_atts([
        'id' => get_the_ID(),
    ], $atts);

    $product_id = intval($atts['id']);
    $product = wc_get_product($product_id);

    if (!$product) {
        return '<p>Produkten hittades inte.</p>';
    }

    $gg_extra = [
        1204 => [
            'title' => 'Detaljer',
            'text' => 'Aurora kombinerar en klassisk solitärring med en mjuk färgton som ger smycket en egen identitet. Den nätta profilen gör ringen bekväm att bära samtidigt som den fungerar lika bra på egen hand som tillsammans med andra ringar.',
            'image' => 'https://www.goldgoblins.se/wp-content/uploads/2026/06/aurora-silverring-830-silver-modellbild-1.webp',
			
           'fields' => [
    'Material' => '830 silver',
    'Sten' => 'Ljusrosa fasetterad sten',
    'Vikt' => '1,4 g',
    'Yta' => 'Polerad',
    'Design' => 'Elegant solitärring med nätt profil',
    'Ursprung' => 'Handgjord i Lidköping, Sverige',
]
        ],
        1210 => [
            'title' => 'Detaljer',
            'text' => 'Sunshine är en handgjord silverring i 830 silver med en champagnefärgad sten. Den eleganta och minimalistiska designen gör ringen till ett tidlöst smycke som passar både vardag och fest.

Den stilrena utformningen gör Sunshine enkel att bära både ensam och tillsammans med andra ringar. Kombinationen av 830 silver och den fasetterade stenen ger ett balanserat uttryck där klassisk design möter moderna detaljer.',
            'image' => 'https://www.goldgoblins.se/wp-content/uploads/2026/06/sunshine-silverring-830-silver-modellbild-1.webp',
			
            'fields' => [
    'Material' => '830 silver',
    'Sten' => 'Gul fasetterad sten',   
    'Vikt' => '2,6 g',   
    'Design' => 'Stilren silverring med klassisk infattning',
    'Ursprung' => 'Handgjord i Lidköping, Sverige',
]
        ],
        1215 => [
            'title' => 'Detaljer',
            'text' => 'Varje Classic-ring tillverkas för hand och får sin egen unika ytstruktur genom den hamrade bearbetningen. Den bredare profilen ger ringen ett stabilt uttryck samtidigt som den organiska formen skapar en mjuk och naturlig känsla.',
            'image' => 'https://www.goldgoblins.se/wp-content/uploads/2026/06/handgjort-halsband-830-silver-hange.webp',
			
            'fields' => [
    'Material' => '830 silver',
    'Sten' => 'Ingen sten',
    'Bredd' => '2-3 mm (beroende på storlek)',
    'Vikt' => '1,2 - 2,7 g (beroende på storlek)',
    'Yta' => 'Hamrad finish',
    'Design' => 'Organiskt formad unisexring',
    'Ursprung' => 'Handgjord i Lidköping, Sverige',
]
        ],
        1216 => [
            'title' => 'Detaljer',
            'text' => 'Edge kännetecknas av sitt avskalade formspråk där skarpa linjer möter en slät och polerad finish. Kombinationen av den släta ytan och de markerade kanterna skapar ett uttryck som känns både modernt och välbalanserat.',
            'image' => 'https://www.goldgoblins.se/wp-content/uploads/2026/06/silverringar-830-silver-pa-hand.webp',
            
			'fields' => [
    'Material' => '830 silver',
    'Sten' => 'Ingen sten',
    'Bredd' => '2,6 mm',
    'Vikt' => '1,6 - 5,4 g (beroende på storlek)',
    'Yta' => 'Slät och polerad',
    'Design' => 'Geometrisk silverring med skarpa linjer',
    'Ursprung' => 'Handgjord i Lidköping, Sverige',
]
        ],
        1213 => [
            'title' => 'Detaljer',
            'text' => 'Robust är utformad med fokus på balans mellan komfort och hållbarhet. Den genomarbetade konstruktionen ger en behaglig passform samtidigt som den bredare silhuetten skapar ett tydligt och sammanhållet uttryck. Ringens handbearbetade yta gör att varje exemplar får sin egen karaktär, vilket bidrar till känslan av ett genuint hantverk.',
            'image' => 'https://www.goldgoblins.se/wp-content/uploads/2026/06/handgjort-halsband-830-silver-med-kors-1.webp',
            
			'fields' => [
    'Material' => '830 silver',
    'Sten' => 'Ingen sten',
    'Bredd' => '4 mm ',
    'Vikt' => '5 - 6 g (beroende på storlek)',
    'Yta' => 'Hamrad finish',
    'Design' => 'Bred silverring med markerad profil',
    'Ursprung' => 'Handgjord i Lidköping, Sverige',
]
        ],
		
		 1217 => [
            'title' => 'Detaljer',
            'text' => 'De proportionerade länkarna ger armbandet ett följsamt rörelsemönster och en behaglig känsla vid användning. Den polerade finishen framhäver de rena formerna och bidrar till ett välbalanserat uttryck utan onödiga detaljer.',
            'image' => 'https://www.goldgoblins.se/wp-content/uploads/2026/06/paperclip-armband-dammodell-1.webp',
            
			 'fields' => [
    'Material' => '830 silver',
    'Sten' => 'Ingen sten',
    'Längd' => '19 cm',
    'Vikt' => '5,25 g',
    'Yta' => 'Polerad',
    'Design' => 'Paperclip-länkar med modern silhuett',
    'Ursprung' => 'Handgjord i Lidköping, Sverige',
]
        ],
		
		 1218 => [
            'title' => 'Detaljer',
            'text' => 'Den generösa längden gör att halsbandet får ett naturligt fall över nyckelbenen och framhäver länkarnas karaktär på ett tydligt sätt. Den polerade finishen ger ett jämnt uttryck där varje del av konstruktionen samverkar för att skapa en välavvägd helhet.',
            'image' => 'https://www.goldgoblins.se/wp-content/uploads/2026/06/paperclip-halsband-herrmodell-1.webp',
            
			 'fields' => [
    'Material' => '830 silver',
    'Sten' => 'Ingen sten',
    'Längd' => '42 cm',
    'Vikt' => '22,5 g',
    'Yta' => 'Polerad',
    'Design' => 'Paperclip-länkar med modern silhuett',
    'Ursprung' => 'Handgjord i Lidköping, Sverige',
]
        ],
		
		1221 => [
            'title' => 'Detaljer',
            'text' => 'Den fasade infattningen omger stenen med rena övergångar och förstärker hängets markerade geometri. Utformningen låter onyxen framträda tydligt samtidigt som silverramen ger balans och struktur åt helheten..',
            'image' => 'https://www.goldgoblins.se/wp-content/uploads/2026/06/handgjort-halsband-830-silver-hange.webp',
            
			'fields' => [
    'Material' => '830 silver',
    'Sten' => 'Svart onyx',
    'Stenvikt' => '4,6 ct',
    'Vikt' => '2,5 g',
    'Infattning' => 'Fasad silverram',
    'Design' => 'Geometriskt hängsmycke med onyx',
    'Ursprung' => 'Handgjord i Lidköping, Sverige',
]
        ],
		
    ];

    $details = $gg_extra[$product_id] ?? [
        'title' => 'Detaljer',
        'text' => $product->get_short_description(),
        'image' => '',
        'material' => 'Silver',
        'stone' => '-',
        'origin' => 'Handgjord i Sverige',
    ];

	$ring_products = [1204, 1210, 1213, 1215, 1216];
$necklace_products = [1221, 1218];

if (in_array($product_id, $ring_products, true)) {
    $size_guide_id = 1524;
} elseif (in_array($product_id, $necklace_products, true)) {
    $size_guide_id = 1525;
} else {
    $size_guide_id = 1524;
}
	
    ob_start();
    ?>

    <div id="gg-product-extra" class="gg-product-extra-wrapper">

    <section id="gg-product-extra-inner" class="gg-product-extra-section">
        <div class="gg-extra-details">
            <h2><?php echo esc_html($details['title']); ?></h2>

            <p><?php echo esc_html($details['text']); ?></p>

           <div class="gg-extra-table">
    <?php foreach ($details['fields'] as $label => $value) : ?>
        <div>
            <span><?php echo esc_html($label); ?></span>
            <strong><?php echo esc_html($value); ?></strong>
        </div>
    <?php endforeach; ?>
</div>

           <div class="gg-extra-links">
    <a href="#" class="gg-open-panel" data-panel="size">Storleksguide →</a>
   <!-- <a href="#" class="gg-open-panel" data-panel="care">Skötselråd →</a> -->
</div>


        </div>

        <?php if (!empty($details['image'])) : ?>
    <div class="gg-extra-image">
        <img src="<?php echo esc_url($details['image']); ?>" alt="">
    </div>
<?php endif; ?>
    </section>
	<div class="gg-info-panel-overlay" aria-hidden="true"></div>

<div class="gg-info-panel" aria-hidden="true">
    <button type="button" class="gg-close-panel" aria-label="Stäng">×</button>

    <div class="gg-panel-content gg-panel-size">
        <?php echo wp_get_attachment_image($size_guide_id, 'large', false, [
            'loading' => 'lazy',
            'decoding' => 'async',
        ]); ?>
    </div>

    <div class="gg-panel-content gg-panel-care">
        <?php echo wp_get_attachment_image(2222, 'large', false, [
            'loading' => 'lazy',
            'decoding' => 'async',
        ]); ?>
    </div>
</div>
	
	
</div>
    <style>
				.gg-product-extra-wrapper {
    width: 100%;

   background-color: #f1dfc4;

background-image:
    radial-gradient(circle at 20% 15%, rgba(255,255,255,0.10), transparent 30%),
    radial-gradient(circle at 80% 35%, rgba(120,90,55,0.03), transparent 35%),
    radial-gradient(circle at 45% 80%, rgba(255,255,255,0.06), transparent 30%),
    linear-gradient(135deg, rgba(255,255,255,0.03), rgba(120,90,55,0.02));
    background-size: cover;
    background-position: center;

    padding: clamp(2rem, 5vw, 4rem) 0;
				border-top: 0px solid #9F8560;
    border-bottom: 3px solid #9F8560;
}
      .gg-product-extra-section {
    width: min(82vw, 62rem);
    margin: 0 auto;
    transition: opacity 0.45s ease;
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: clamp(2rem, 5vw, 5rem);
}

        .gg-extra-details h2 {
            font-family: 'PT Serif', serif;
            color: #9F8560;
            text-transform: uppercase;
            letter-spacing: clamp(0.08rem, 0.18vw, 0.14rem);
            font-size: clamp(0.9rem, 1.2vw, 1.2rem);
            font-weight: 500;
            margin: 0 0 clamp(1rem, 2vw, 2rem);
        }

        .gg-extra-details p,
        .gg-extra-table,
        .gg-extra-links a {
            font-family: 'PT Serif', serif;
            color: #2f2b25;
            font-size: clamp(12px, 1vw, 16px);
            line-height: 1.65;
        }

        .gg-extra-details p {
            margin: 0 0 clamp(1.5rem, 3vw, 2.5rem);
        }

        .gg-extra-table div {
            display: grid;
            grid-template-columns: 1fr 1.5fr;
            gap: 1rem;
            border-bottom: 1px solid #9F8560;
            padding: clamp(0.45rem, 1vw, 0.8rem) 0;
        }

        .gg-extra-table span {
            text-transform: uppercase;
            letter-spacing: 0.08em;
            font-size: 0.8em;
			color: #9F8560;
        }

        .gg-extra-table strong {
            font-weight: 400;
			color: #2f2b25;
        }

        .gg-extra-links {
            display: flex;
            gap: clamp(1rem, 2vw, 2rem);
            margin-top: clamp(1rem, 2vw, 2rem);
        }

        .gg-extra-links a {
    color: #B9965F;
    text-decoration: none;
    border-bottom: 1px solid #B9965F;

    position: relative;
    display: inline-block;
    width: fit-content;
    z-index: 1;
}
	.gg-extra-links a::before {
    content: "";
    position: absolute;
    left: 50%;
    top: 50%;

    width: calc(100% + 12px);
    height: 1.4em;

    transform: translate(-50%, -50%) scale(0.7);

    background: radial-gradient(
        ellipse at center,
        rgba(185,150,95,0.35) 0%,
        rgba(185,150,95,0.15) 50%,
        rgba(185,150,95,0) 100%
    );

    border-radius: 999px;
    filter: blur(6px);

    opacity: 0;
    transition: opacity 0.25s ease,
                transform 0.25s ease;

    pointer-events: none;
    z-index: -1;
}

.gg-extra-links a:hover::before {
    opacity: 1;
    transform: translate(-50%, -50%) scale(1);
}

        .gg-extra-image img {
            width: 100%;
            aspect-ratio: 4 / 3;
            object-fit: cover;
            display: block;
        }

        @media (max-width: 800px) {
            .gg-product-extra-section {
                grid-template-columns: 1fr;
            }
        }
	
	.gg-info-panel-overlay{
    position:fixed;
    inset:0;
    background:rgba(0,0,0,0.35);
    opacity:0;
    visibility:hidden;
    transition:opacity 0.3s ease, visibility 0.3s ease;
    z-index:9998;
}

.gg-info-panel{
    position:fixed;
    top:0;
    right:0;
    width:min(95vw, 44%);
    height:100vh;
    background:#f1dfc4;
    border-left:3px solid #9F8560;
    box-shadow:-10px 0 30px rgba(0,0,0,0.25);
    transform:translateX(100%);
    transition:transform 0.35s ease;
    z-index:9999;
    padding:3rem 1.5rem 1.5rem;
    box-sizing:border-box;
    overflow-y:auto;
}

.gg-info-panel.is-open{
    transform:translateX(0);
}

.gg-info-panel-overlay.is-open{
    opacity:1;
    visibility:visible;
}

.gg-close-panel{
    position:absolute;
    top:1rem;
    right:1rem;
    background:none;
    border:0;
    font-size:2rem;
    line-height:1;
    cursor:pointer;
    color:#9F8560;
}

.gg-panel-content{
    display:none;
}

.gg-panel-content.is-active{
    display:block;
}

.gg-panel-content img{
    width:100%;
    height:auto;
    display:block;
}
    </style>

		<script>
document.addEventListener('click', function(e) {
    const openLink = e.target.closest('.gg-open-panel');
    const closeBtn = e.target.closest('.gg-close-panel');
    const overlay = e.target.closest('.gg-info-panel-overlay');

    const panel = document.querySelector('.gg-info-panel');
    const panelOverlay = document.querySelector('.gg-info-panel-overlay');

    if (!panel || !panelOverlay) return;

    if (openLink) {
        e.preventDefault();

        const type = openLink.dataset.panel;

        document.querySelectorAll('.gg-panel-content').forEach(function(content) {
            content.classList.remove('is-active');
        });

        const activeContent = document.querySelector('.gg-panel-' + type);
        if (activeContent) {
            activeContent.classList.add('is-active');
        }

        panel.classList.add('is-open');
        panelOverlay.classList.add('is-open');
        panel.setAttribute('aria-hidden', 'false');
        panelOverlay.setAttribute('aria-hidden', 'false');
    }

    if (closeBtn || overlay) {
        panel.classList.remove('is-open');
        panelOverlay.classList.remove('is-open');
        panel.setAttribute('aria-hidden', 'true');
        panelOverlay.setAttribute('aria-hidden', 'true');
    }
});
</script>
		
    <?php
    return ob_get_clean();
});

add_action('wp_ajax_gg_load_product_extra', 'gg_load_product_extra_ajax');
add_action('wp_ajax_nopriv_gg_load_product_extra', 'gg_load_product_extra_ajax');

function gg_load_product_extra_ajax() {
    if (!isset($_POST['product_id'])) {
        wp_die('Produkt-ID saknas.');
    }

    $product_id = intval($_POST['product_id']);

    echo do_shortcode('[goblin_product_extra id="' . $product_id . '"]');

    wp_die();
}

/**
 * Gold Goblins Header
 */
add_shortcode('gg_header', function() {
    ob_start();
    ?>

   <div class="gg-hero">
    <div class="gg-hero-nav">
        <div class="gg-menu-left">
            <a href="https://www.goldgoblins.se/ringar/">RINGAR</a>
            <a href="https://www.goldgoblins.se/armband/">ARMBAND</a>
            <a href="https://www.goldgoblins.se/halsband/">HALSBAND</a>
            <a href="https://www.goldgoblins.se/hangsmycke/">HÄNGSMYCKE</a>
        </div>

        <div class="gg-logo-area">
            <a href="https://www.goldgoblins.se/">
                <img
    class="gg-logo-img"
    src="https://www.goldgoblins.se/wp-content/uploads/2026/06/Gold_Goblins_Logga.webp"
    alt="Gold Goblins"
    width="240"
    height="240"
    decoding="async"
>
            </a>

            <div class="gg-logo-title">GOLD GOBLINS</div>

           <div class="gg-logo-decor">
    <img class="gg-script-img" src="https://www.goldgoblins.se/wp-content/uploads/2026/06/ggloggar233endered2.webp" alt="">
</div>
        </div>

        <div class="gg-menu-right">
            <a href="https://www.goldgoblins.se/vardering/">VÄRDERING</a>
            <a href="https://www.goldgoblins.se/var-verksamhet/">VÅR VERKSAMHET</a>
            <a href="https://www.goldgoblins.se/kontakta-oss/">KONTAKTA OSS</a>
<a href="#" class="gg-cart-trigger" aria-label="Öppna varukorg">

<svg class="gg-cart-icon" xmlns="http://www.w3.org/2000/svg"
width="24" height="24" viewBox="0 0 24 24"
fill="none" stroke="currentColor" stroke-width="2"
stroke-linecap="round" stroke-linejoin="round">

    <path stroke="none" d="M0 0h24v24H0z" fill="none" />
    <path d="M9.5 3h5a1.5 1.5 0 0 1 1.5 1.5a3.5 3.5 0 0 1 -3.5 3.5h-1a3.5 3.5 0 0 1 -3.5 -3.5a1.5 1.5 0 0 1 1.5 -1.5" />
    <path d="M4 17v-1a8 8 0 1 1 16 0v1a4 4 0 0 1 -4 4h-8a4 4 0 0 1 -4 -4" />

</svg>

<span class="gg-cart-count" style="display:none;"></span>

</a>
        </div>
    </div>
</div>
<div id="gg-cart-overlay"></div>

<aside id="gg-side-cart">
    <div class="gg-side-cart-header">
        <div class="gg-side-cart-title">Varukorg</div>
        <button id="gg-cart-close" type="button">×</button>
    </div>

    <div id="gg-side-cart-content">
        <p>Din varukorg visas här.</p>
    </div>

    <a href="https://www.goldgoblins.se/varukorg/" class="gg-side-cart-link">
        Visa varukorg
    </a>
</aside>
<style>
.gg-hero {
    position: relative;
    width: 100%;
    min-height: unset;

    background-color: #f1dfc4;
    background-image:
        radial-gradient(circle at 20% 15%, rgba(255,255,255,0.10), transparent 30%),
        radial-gradient(circle at 80% 35%, rgba(120,90,55,0.03), transparent 35%),
        radial-gradient(circle at 45% 80%, rgba(255,255,255,0.06), transparent 30%),
        linear-gradient(135deg, rgba(255,255,255,0.03), rgba(120,90,55,0.02));

    border-bottom: 0;
}
	
	.gg-hero::after {
    content: "";
    position: absolute;
    left: 0;
    right: 0;
    bottom: 0;

    height: 1px;

    background: linear-gradient(
        90deg,
        transparent 0%,
        rgba(159,133,96,0.28) 18%,
        rgba(159,133,96,0.70) 50%,
        rgba(159,133,96,0.28) 82%,
        transparent 100%
    );

    pointer-events: none;
}


.gg-cart-trigger {
    position: relative;
    display: inline-flex;
    align-items: center;
    justify-content: center;
}

.gg-cart-trigger {
    display: flex;
    align-items: center;
    gap: clamp(3px, 0.3vw, 6px);
}

.gg-cart-count {
     position: absolute;
right: -1.0em;

    color: #B9965F;

    font-family: 'PT Serif', serif;
    font-size: clamp(8px, 0.65vw, 11px);
    font-weight: 500;

    line-height: 1;
}

.gg-cart-icon {
    position: relative;

    top: -0.12em;

    width: clamp(14px, 1vw, 16px);
    height: clamp(14px, 1vw, 16px);

    color: #2b2b2b;

    transition:
        color .25s ease,
        transform .25s ease;
}

.gg-cart-trigger:hover .gg-cart-icon {
    color: #aa8a58;
    transform: scale(1.08);
}

.gg-cart-count {
    font-size: clamp(8px, 0.65vw, 11px);
    color: #aa8a58;
}

	.gg-side-cart-title {
    margin: 0;

    color: #B9965F;

    font-family: 'PT Serif', serif;
    font-size: 0.85rem;

    text-transform: uppercase;
    letter-spacing: 0.14em;

    font-weight: 500;
}
	
#gg-cart-overlay {
    position: fixed;
    inset: 0;
    background: rgba(0,0,0,0.35);
    opacity: 0;
    visibility: hidden;
    transition: 0.3s ease;
    z-index: 99998;
}

#gg-cart-overlay.open {
    opacity: 1;
    visibility: visible;
}

#gg-side-cart {
    position: fixed;
    top: 0;
    right: -420px;
    width: min(420px, 92vw);
    height: 100vh;
    background-color: #f1dfc4;
    border-left: 2px solid #aa8a58;
    z-index: 99999;
    transition: right 0.35s ease;
    padding: 24px;
    display: flex;
    flex-direction: column;
}

#gg-side-cart.open {
    right: 0;
}

.gg-side-cart-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-family: 'PT Serif', serif;
}

#gg-cart-close {
    background: none;
    border: 0;
    font-size: 28px;
    cursor: pointer;
    color: #3a2c1f;

    transition:
        color 0.25s ease,
        transform 0.25s ease;
}

#gg-cart-close:hover {
    color: #aa8a58;
    transform: scale(1.25) rotate(90deg);
}

#gg-side-cart-content {
    flex: 1;
    margin-top: 24px;
    font-family: 'PT Serif', serif;
    display: flex;
    flex-direction: column;
    gap: 0;
}

.gg-side-cart-item {
    width: 100%;
    display: grid;
    grid-template-columns: 72px 1fr auto;
    gap: 14px;
    align-items: center;
    padding: 14px 0;
    border-bottom: 1px solid rgba(170,138,88,0.35);
    transition: background 0.2s ease;
}

.gg-side-cart-item:hover {
    background: rgba(170,138,88,0.06);
}

.gg-side-cart-thumb img {
    width: 64px;
    height: 64px;
    object-fit: cover;
    display: block;
}

.gg-side-cart-item-title {
    font-family: 'PT Serif', serif;
    font-size: 0.9rem;
    line-height: 1.25;
}

.gg-side-cart-item-meta {
    margin-top: 4px;
    font-size: 0.85rem;
    color: #8a6f45;
}

.gg-side-cart-remove {
    background: none;
    border: 0;
    color: #3a2c1f;
    font-size: 22px;
    cursor: pointer;
    line-height: 1;

    transition:
        color 0.2s ease,
        transform 0.2s ease;
}

.gg-side-cart-remove:hover {
    color: #aa8a58;
    transform: scale(1.25) rotate(90deg);
}

.gg-side-cart-total {
    display: flex;
    justify-content: space-between;

    margin-top: auto;

    padding-top: 18px;
    padding-bottom: 18px;

    border-top: 2px solid #aa8a58;

    font-family: 'PT Serif', serif;
    font-size: 1rem;
}
			  
.gg-side-cart-link {
    display: flex;
    justify-content: center;
    align-items: center;

    padding: 10px 18px;

    border: 2px solid #aa8a58;
    color: #3a2c1f;

    text-decoration: none;
    font-family: Georgia, "Times New Roman", serif;
    font-size: clamp(12px, 0.8vw, 15px);
    text-transform: uppercase;
    letter-spacing: 0.08em;

    cursor: pointer;

    background-color: #f1dfc4;
    background-image:
        radial-gradient(circle at 20% 15%, rgba(255,255,255,0.10), transparent 30%),
        radial-gradient(circle at 80% 35%, rgba(120,90,55,0.03), transparent 35%),
        radial-gradient(circle at 45% 80%, rgba(255,255,255,0.06), transparent 30%),
        linear-gradient(135deg, rgba(255,255,255,0.03), rgba(120,90,55,0.02));

    background-size: cover;
    background-position: center;

    transition: all 0.25s ease;
}
			  
			  .gg-side-cart-link:hover {
    transform: translateY(-1px);
    border-color: #c4a26d;
	color: #B9965F;			  
    box-shadow: 0 4px 12px rgba(0,0,0,0.08);
}

.gg-hero-nav {
    width: 90%;
    margin: 0 auto;
    padding-top: clamp(8px, 1vw, 16px);
    padding-bottom: clamp(6px, 0.8vw, 12px);

    display: grid;
    grid-template-columns: 1fr auto 1fr;
    align-items: start;
}

.gg-menu-left,
.gg-menu-right {
    display: flex;
    gap: clamp(8px, 1.8vw, 32px);
    padding-top: clamp(20px, 3vw, 45px);
}

.gg-menu-right {
    justify-content: flex-end;
}

.gg-menu-left a,
.gg-menu-right a {
    text-decoration: none;
    color: #2b2b2b;
    font-family: 'PT Serif', serif;
    font-size: clamp(8px, 0.75vw, 13px);
    letter-spacing: clamp(1px, 0.15vw, 3px);
    white-space: nowrap;
	transition: color 0.25s ease;
	
}

			  .gg-menu-left a:hover,
.gg-menu-right a:hover {
    color: #B9965F;
}
			  
.gg-logo-area {
    text-align: center;
}

.gg-logo-img {
    width: clamp(62px, 4.4vw, 92px);
    height: auto;
}

.gg-logo-title {
    font-family: 'PT Serif', serif;
    font-size: clamp(18px, 1.8vw, 30px);
    letter-spacing: clamp(3px, 0.45vw, 7px);
    color: #2b2b2b;
    white-space: nowrap;
}

.gg-logo-decor {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 0;
}

.gg-script-img {
    width: clamp(120px, 11vw, 160px);
    height: auto;
}

			  
	.gg-side-cart-qty {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    margin-top: 6px;
}

.gg-side-cart-qty button {
    width: 22px;
    height: 22px;
    border: 1px solid #aa8a58;
    background: transparent;
    color: #3a2c1f;
    cursor: pointer;
    font-family: Georgia, "Times New Roman", serif;
    line-height: 1;
}

.gg-side-cart-qty button:hover {
    color: #aa8a58;
    transform: scale(1.08);
}

.gg-side-cart-price {
    margin-top: 5px;
    color: #8a6f45;
}		  
			  
			  .gg-side-cart-qty-static {
    margin-top: 6px;
    font-size: 0.85rem;
    color: #8a6f45;
    font-family: 'PT Serif', serif;
}
			  

			
	@media (max-width:700px){

    html,
    body{
        width:100%;
        max-width:100%;
        margin:0;
        padding:0;
        overflow-x:hidden;
    }

    .gg-hero{
        width:100vw;
        max-width:100vw;
        margin:0;
        overflow:hidden;
    }

    .gg-hero-nav{
        width:100%;
        max-width:100%;
        margin:0;
        padding:14px 12px;
        box-sizing:border-box;
        display:flex;
        flex-direction:column;
        align-items:center;
        gap:10px;
    }

    .gg-logo-area{
        order:1;
        width:100%;
        text-align:center;
    }

    .gg-menu-left,
    .gg-menu-right{
        order:2;
        width:100%;
        display:flex;
        flex-wrap:wrap;
        justify-content:center;
        align-items:center;
        gap:10px 14px;
        padding:0;
        box-sizing:border-box;
    }

    .gg-menu-left a,
    .gg-menu-right a{
        font-size:10px;
        letter-spacing:1px;
        white-space:normal;
    }

    .gg-logo-img{
        width:64px;
    }

    .gg-logo-title{
        font-size:18px;
        letter-spacing:3px;
        white-space:normal;
    }

    .gg-script-img,
    .gg-arrow-img{
        display:none;
    }

    .gg-cart-trigger{
        display:inline-flex;
    }

    #gg-side-cart{
        width:92vw;
        right:-92vw;
    }

    #gg-side-cart.open{
        right:0;
    }
}
			  
			  
</style>

<script>
document.addEventListener('click', function(e) {
    const trigger = e.target.closest('.gg-cart-trigger');
    const close = e.target.closest('#gg-cart-close');
    const overlay = e.target.closest('#gg-cart-overlay');

    const cart = document.getElementById('gg-side-cart');
    const bg = document.getElementById('gg-cart-overlay');

    if (trigger) {
        e.preventDefault();
ggLoadSideCart();
        cart.classList.add('open');
        bg.classList.add('open');
    }

    if (close || overlay) {
        cart.classList.remove('open');
        bg.classList.remove('open');
    }
});

function ggLoadSideCart() {
    const content = document.getElementById('gg-side-cart-content');

    if (!content) return;

    content.innerHTML = '<p>Laddar varukorg...</p>';

    fetch('/wp-admin/admin-ajax.php?action=gg_get_side_cart', {
        credentials: 'same-origin'
    })
    .then(response => response.text())
    .then(html => {
        content.innerHTML = html;
    });
}

function ggUpdateCartCount() {
    const countEl = document.querySelector('.gg-cart-count');

    if (!countEl) return;

    fetch('/wp-admin/admin-ajax.php?action=gg_get_cart_count', {
        credentials: 'same-origin'
    })
    .then(response => response.text())
    .then(count => {
    count = parseInt(count.trim(), 10);

    if (count > 0) {
        countEl.textContent = count;
        countEl.style.display = 'inline';
    } else {
        countEl.style.display = 'none';
    }
});
}

document.addEventListener('DOMContentLoaded', ggUpdateCartCount);
document.body.addEventListener('wc_fragment_refresh', ggUpdateCartCount);
			  
			  document.addEventListener('click', function(e) {
    const removeBtn = e.target.closest('.gg-side-cart-remove');

    if (!removeBtn) return;

    e.preventDefault();

    const formData = new FormData();
    formData.append('action', 'gg_remove_cart_item');
    formData.append('cart_key', removeBtn.dataset.cartKey);

    fetch('/wp-admin/admin-ajax.php', {
        method: 'POST',
        body: formData,
        credentials: 'same-origin'
    })
    .then(() => {
        ggLoadSideCart();
        ggUpdateCartCount();
    });
});
		
	document.addEventListener('click', function(e) {
    const minus = e.target.closest('.gg-cart-qty-minus');
    const plus = e.target.closest('.gg-cart-qty-plus');

    if (!minus && !plus) return;

    e.preventDefault();

    const btn = minus || plus;
    const change = plus ? 1 : -1;

    const formData = new FormData();
    formData.append('action', 'gg_update_cart_qty');
    formData.append('cart_key', btn.dataset.cartKey);
    formData.append('change', change);

    fetch('/wp-admin/admin-ajax.php', {
        method: 'POST',
        body: formData,
        credentials: 'same-origin'
    })
    .then(() => {
        ggLoadSideCart();
        ggUpdateCartCount();
    });
});		  
			  
</script>

    <?php
    return ob_get_clean();
});

/**
 * Gold Goblins Varukorg
 */
add_shortcode('gg_cart', function() {

    ob_start();
    ?>

    <section class="gg-cart-page">
        <div class="gg-cart-inner">
            <?php echo do_shortcode('[woocommerce_cart]'); ?>
        </div>
    </section>

    <style>
    .gg-cart-page {
        min-height: auto;
        padding: clamp(0.5rem, 1.5vw, 1.5rem) 0 clamp(1.5rem, 3vw, 3rem);

        background-color: #f1dfc4;
        background-image:
            radial-gradient(circle at 20% 15%, rgba(255,255,255,0.22), transparent 28%),
            radial-gradient(circle at 80% 35%, rgba(120,90,55,0.08), transparent 32%),
            radial-gradient(circle at 45% 80%, rgba(255,255,255,0.14), transparent 30%),
            linear-gradient(135deg, rgba(255,255,255,0.10), rgba(120,90,55,0.05));
        background-size: cover;
        background-position: center;
    }

    .gg-cart-inner {
        width: min(94vw, 90rem);
        margin: 0 auto;
        font-family: 'PT Serif', serif;
        font-size: clamp(0.78rem, 0.85vw, 0.95rem);
    }

    .gg-cart-inner .woocommerce {
        display: grid;
        grid-template-columns: minmax(0, 1.45fr) minmax(320px, 0.55fr);
        gap: clamp(3rem, 6vw, 6rem);
        align-items: start;
    }

    .gg-cart-inner .woocommerce-cart-form {
        grid-column: 1;
        width: 100%;
    }

    .gg-cart-inner .cart-collaterals {
        grid-column: 2;
        width: 100% !important;
        padding-left: clamp(1rem, 2vw, 2rem);
    }

    .gg-cart-inner .cart-collaterals .cart_totals {
        width: 100% !important;
        float: none !important;
        margin: 0 !important;
    }

    .gg-cart-inner table.shop_table {
        width: 100%;
        border: 0 !important;
        background: transparent !important;
        margin: 0 !important;
    }

    .gg-cart-inner table.shop_table th {
        color: #B9965F;
        text-transform: uppercase;
        letter-spacing: clamp(0.08rem, 0.14vw, 0.14rem);
        font-size: clamp(0.65rem, 0.7vw, 0.82rem);
        font-weight: 500;
        padding: clamp(0.45rem, 0.8vw, 0.8rem) clamp(0.4rem, 0.8vw, 0.8rem);
        border-bottom: 1px solid rgba(170,138,88,0.35) !important;
    }

    .gg-cart-inner table.shop_table td {
        padding: clamp(0.55rem, 1vw, 1rem) clamp(0.4rem, 0.8vw, 0.8rem) !important;
        border-bottom: 1px solid rgba(170,138,88,0.25) !important;
    }

    .gg-cart-inner .product-thumbnail img {
        width: clamp(38px, 4vw, 58px) !important;
        height: clamp(38px, 4vw, 58px) !important;
        object-fit: cover;
    }

    .gg-cart-inner .product-name a {
        color: #2b2b2b;
        text-decoration: none;
        font-size: clamp(0.78rem, 0.85vw, 0.95rem);
    }

    .gg-cart-inner .cart_totals {
        font-size: clamp(0.78rem, 0.85vw, 0.95rem);
    }

    .gg-cart-inner .cart_totals h2 {
        color: #B9965F !important;
        font-size: clamp(12px, 0.85vw, 17px) !important;
        letter-spacing: 0.25em;
        text-transform: uppercase;
        font-weight: 400 !important;
        line-height: 1.4;
        margin: 0 0 clamp(0.7rem, 1vw, 1rem);
    }

    .gg-cart-inner .checkout-button,
    .gg-cart-inner button[name="update_cart"] {
        padding: clamp(0.55rem, 0.9vw, 0.85rem) clamp(1rem, 2vw, 1.8rem) !important;
        font-size: clamp(0.75rem, 0.9vw, 0.95rem) !important;

        background-color: #f1dfc4 !important;
        color: #3a2c1f !important;
        border: 2px solid #aa8a58 !important;
        border-radius: 0 !important;

        font-family: Georgia, "Times New Roman", serif !important;
        text-transform: uppercase;
        letter-spacing: 0.08em;

        transition: all 0.25s ease;
    }

    .gg-cart-inner .checkout-button:hover,
    .gg-cart-inner button[name="update_cart"]:hover {
        transform: translateY(-1px);
        border-color: #c4a26d !important;
        box-shadow: 0 4px 12px rgba(0,0,0,0.08);
    }

    .gg-cart-inner .woocommerce-cart-form table.cart td.actions {
        padding-top: clamp(4.5rem, 8vw, 8rem) !important;
        text-align: left !important;
        border-bottom: 0 !important;
    }

    .gg-cart-inner .woocommerce-cart-form table.cart td.actions button[name="update_cart"] {
        float: none !important;
        display: inline-flex !important;
        justify-content: center;
        align-items: center;
        width: clamp(14rem, 22vw, 20rem);
        margin-left: 0 !important;
    }

    .gg-cart-inner .cart_totals,
    .gg-cart-inner .cart_totals *,
    .gg-cart-inner .wc-proceed-to-checkout,
    .gg-cart-inner .wc-proceed-to-checkout * {
        font-family: 'PT Serif', serif !important;
    }

    .gg-cart-inner .cart_totals table.shop_table th {
        color: #B9965F !important;
        font-size: clamp(11px, 0.8vw, 15px) !important;
        letter-spacing: 0.18em;
        text-transform: uppercase;
        font-weight: 400 !important;
        line-height: 1.5;
    }

    .gg-cart-inner .cart_totals table.shop_table td,
    .gg-cart-inner .cart_totals table.shop_table td span,
    .gg-cart-inner .cart_totals table.shop_table td strong,
    .gg-cart-inner .cart_totals table.shop_table td p {
        color: #2b2b2b !important;
        font-size: clamp(12px, 0.85vw, 16px) !important;
        letter-spacing: 0.04em;
        font-weight: 400 !important;
        line-height: 1.6;
        text-transform: none !important;
    }

    .gg-cart-inner .cart_totals .order-total td,
    .gg-cart-inner .cart_totals .order-total td strong,
    .gg-cart-inner .cart_totals .order-total td .amount {
        color: #2b2b2b !important;
        font-size: clamp(14px, 1vw, 20px) !important;
        letter-spacing: 0.06em;
        font-weight: 500 !important;
        text-transform: none !important;
    }

    .gg-cart-inner .wc-proceed-to-checkout .wcppec-checkout-buttons__separator,
    .gg-cart-inner .wc-proceed-to-checkout p,
    .gg-cart-inner .cart_totals .wc-proceed-to-checkout p {
        color: #2b2b2b !important;
        font-size: clamp(11px, 0.75vw, 14px) !important;
        letter-spacing: 0.02em;
        font-weight: 400 !important;
        line-height: 1.4;
    }

    .gg-cart-inner .cart_totals a:not(.checkout-button) {
        color: #2b2b2b !important;
        text-decoration: underline;
        text-underline-offset: 3px;
    }

    .gg-cart-inner .cart_totals a:hover {
        color: #B9965F !important;
    }

    .gg-cart-inner .checkout-button {
        margin-top: clamp(0.8rem, 1.5vw, 1.5rem) !important;
        text-decoration: none !important;
    }

  /* Quantity +/- i varukorgen */

.gg-cart-qty-wrap {
    display: inline-flex;
    align-items: center;
    gap: clamp(0.35rem, 0.6vw, 0.7rem);
}

.gg-cart-qty-btn {
    background: transparent;
    border: 0;
    color: #B9965F;
    font-family: 'PT Serif', serif;
    font-size: clamp(1rem, 1vw, 1.25rem);
    line-height: 1;
    cursor: pointer;
    padding: 0;
    transition: color 0.2s ease, transform 0.2s ease;
}

.gg-cart-qty-btn:hover {
    color: #3a2c1f;
    transform: scale(1.18);
}

.gg-cart-inner input.qty::-webkit-outer-spin-button,
.gg-cart-inner input.qty::-webkit-inner-spin-button {
    -webkit-appearance: none;
    margin: 0;
}

.gg-cart-inner input.qty {
    appearance: textfield;
    -moz-appearance: textfield;

    width: clamp(1.4rem, 1.8vw, 2rem) !important;
    padding: 0 !important;

    background: transparent !important;
    border: 0 !important;
    box-shadow: none !important;
    outline: none !important;

    color: #2b2b2b !important;
    font-family: 'PT Serif', serif !important;
    font-size: clamp(0.8rem, 0.85vw, 1rem) !important;
    text-align: center;
}

    @media (max-width: 900px) {
        .gg-cart-inner .woocommerce {
            grid-template-columns: 1fr;
        }

        .gg-cart-inner .woocommerce-cart-form,
        .gg-cart-inner .cart-collaterals {
            grid-column: 1;
        }

        .gg-cart-inner .cart-collaterals {
            padding-left: 0;
        }

        .gg-cart-inner .woocommerce-cart-form table.cart td.actions {
            padding-top: clamp(2rem, 5vw, 4rem) !important;
        }
    }
	
	/* WooCommerce notices */

.gg-cart-inner .woocommerce-message,
.gg-cart-inner .woocommerce-info,
.gg-cart-inner .woocommerce-error {
    background: transparent !important;
    border-top: 2px solid #B9965F !important;
    border-bottom: 1px solid rgba(170,138,88,0.35) !important;
    border-left: 0 !important;
    border-right: 0 !important;

    color: #2b2b2b !important;

    font-family: 'PT Serif', serif !important;
    font-size: clamp(12px, 0.85vw, 16px) !important;
    letter-spacing: 0.05em;

    padding: clamp(0.8rem, 1vw, 1.2rem) !important;
    margin-bottom: 0.5rem !important;
}

/* Ikonen */
.gg-cart-inner .woocommerce-message::before {
    display: none !important;
}

.gg-cart-inner .woocommerce-message {
    padding-left: 0 !important;
}

/* Ta bort eventuell grön standardfärg */
.gg-cart-inner .woocommerce-message {
    border-top-color: #B9965F !important;
}

/* Gör WooCommerce loader transparent */
	.blockUI.blockOverlay {
    background: transparent !important;
    opacity: 0 !important;
}

.blockUI.blockOverlay::before {
    opacity: 1 !important;
}
	
	

	
    </style>

		
<script>
function ggInitCartQtyControls() {
    document.querySelectorAll('.gg-cart-inner input.qty').forEach(function(input) {
        if (input.closest('.gg-cart-qty-wrap')) return;

        const wrapper = document.createElement('div');
        wrapper.className = 'gg-cart-qty-wrap';

        const minus = document.createElement('button');
        minus.type = 'button';
        minus.className = 'gg-cart-qty-btn gg-cart-qty-minus';
        minus.textContent = '−';

        const plus = document.createElement('button');
        plus.type = 'button';
        plus.className = 'gg-cart-qty-btn gg-cart-qty-plus';
        plus.textContent = '+';

        input.parentNode.insertBefore(wrapper, input);
        wrapper.appendChild(minus);
        wrapper.appendChild(input);
        wrapper.appendChild(plus);
    });
}

ggInitCartQtyControls();

document.addEventListener('DOMContentLoaded', ggInitCartQtyControls);

if (window.jQuery) {
    jQuery(document.body).on('updated_wc_div updated_cart_totals', function() {
        ggInitCartQtyControls();
    });
}

document.addEventListener('click', function(e) {
    const minus = e.target.closest('.gg-cart-qty-minus');
    const plus = e.target.closest('.gg-cart-qty-plus');

    if (!minus && !plus) return;

    const wrapper = e.target.closest('.gg-cart-qty-wrap');
    const input = wrapper.querySelector('input.qty');

    let value = parseInt(input.value, 10) || 1;
    const min = parseInt(input.getAttribute('min'), 10) || 0;
    const max = parseInt(input.getAttribute('max'), 10);

    if (minus) {
        value = Math.max(min, value - 1);
    }

    if (plus) {
        value = isNaN(max) ? value + 1 : Math.min(max, value + 1);
    }

    input.value = value;
    input.dispatchEvent(new Event('change', { bubbles: true }));

    const updateBtn = document.querySelector('.gg-cart-inner button[name="update_cart"]');

    if (updateBtn) {
        updateBtn.disabled = false;
    }
});
	
	

	
</script>
		
	
    <?php
    return ob_get_clean();
});

/**
 * Gold Goblins Kassa
 */
add_action('wp_enqueue_scripts', function() {
    if (is_checkout()) {
        wp_enqueue_script('selectWoo');
        wp_enqueue_style('select2');
    }
});

add_filter('woocommerce_cart_item_name', function($name, $cart_item, $cart_item_key) {

    if (!is_checkout()) {
        return $name;
    }

    $product = $cart_item['data'];

    if (!$product) {
        return $name;
    }

    $thumb = $product->get_image('thumbnail');

    return '<span class="gg-checkout-product-line">' .
        '<span class="gg-checkout-product-thumb">' . $thumb . '</span>' .
        '<span class="gg-checkout-product-name">' . $name . '</span>' .
    '</span>';

}, 10, 3);



add_shortcode('gg_checkout', function() {

    ob_start();
    ?>

    <section class="gg-checkout-page">
        <div class="gg-checkout-inner">
            <?php echo do_shortcode('[woocommerce_checkout]'); ?>
        </div>
    </section>

    <style>
    .gg-checkout-page {
         padding: clamp(1rem, 2vw, 2rem) 0 0;
    margin-bottom: -6rem;

        background-color: #f1dfc4;
        background-image:
            radial-gradient(circle at 20% 15%, rgba(255,255,255,0.22), transparent 28%),
            radial-gradient(circle at 80% 35%, rgba(120,90,55,0.08), transparent 32%),
            radial-gradient(circle at 45% 80%, rgba(255,255,255,0.14), transparent 30%),
            linear-gradient(135deg, rgba(255,255,255,0.10), rgba(120,90,55,0.05));
        background-size: cover;
        background-position: center;
    }

    .gg-checkout-inner {
        width: min(94vw, 90rem);
        margin: 0 auto;
        font-family: 'PT Serif', serif;
        font-size: clamp(12px, 0.85vw, 16px);
        color: #2b2b2b;
		transform: scale(0.9);
    transform-origin: top center;
    }

    .gg-checkout-inner form.checkout {
        display: grid;
        grid-template-columns: minmax(0, 1.25fr) minmax(320px, 0.75fr);
        gap: clamp(3rem, 6vw, 6rem);
        align-items: start;
    }

    .gg-checkout-inner #customer_details {
        grid-column: 1;
    }

    .gg-checkout-inner #order_review_heading,
    .gg-checkout-inner #order_review {
        grid-column: 2;
    }

    .gg-checkout-inner h3,
    .gg-checkout-inner #order_review_heading {
        color: #B9965F;
        font-family: 'PT Serif', serif;
        font-size: clamp(12px, 0.85vw, 17px);
        letter-spacing: 0.25em;
        text-transform: uppercase;
        font-weight: 400;
        margin: 0 0 clamp(1rem, 1.5vw, 1.5rem);
    }

    .gg-checkout-inner label {
        color: #B9965F;
        font-family: 'PT Serif', serif;
        font-size: clamp(11px, 0.8vw, 15px);
        letter-spacing: 0.14em;
        text-transform: uppercase;
        font-weight: 400;
        line-height: 1.5;
    }

    .gg-checkout-inner input.input-text,
    .gg-checkout-inner textarea,
    .gg-checkout-inner select {
        width: 100%;
        background: transparent !important;
        border: 1px solid rgba(170,138,88,0.45) !important;
        border-radius: 0 !important;

        color: #2b2b2b !important;
        font-family: 'PT Serif', serif !important;
        font-size: clamp(12px, 0.85vw, 16px) !important;
        letter-spacing: 0.04em;

        padding: clamp(0.45rem, 0.8vw, 0.75rem) !important;
        box-shadow: none !important;
    }

    .gg-checkout-inner input:focus,
    .gg-checkout-inner textarea:focus,
    .gg-checkout-inner select:focus {
        outline: none !important;
        border-color: #B9965F !important;
    }

    .gg-checkout-inner .form-row {
        margin-bottom: clamp(0.8rem, 1.2vw, 1.3rem) !important;
    }

    .gg-checkout-inner table.shop_table {
        width: 100%;
        border: 0 !important;
        background: transparent !important;
        margin: 0 0 clamp(1.2rem, 2vw, 2rem) !important;
    }

    .gg-checkout-inner table.shop_table th {
        color: #B9965F !important;
        font-size: clamp(11px, 0.8vw, 15px) !important;
        letter-spacing: 0.18em;
        text-transform: uppercase;
        font-weight: 400 !important;
        border-bottom: 1px solid rgba(170,138,88,0.35) !important;
        padding: clamp(0.7rem, 1vw, 1rem) 0 !important;
    }

    .gg-checkout-inner table.shop_table td {
        color: #2b2b2b !important;
        font-size: clamp(12px, 0.85vw, 16px) !important;
        letter-spacing: 0.04em;
        font-weight: 400 !important;
        border-bottom: 1px solid rgba(170,138,88,0.25) !important;
        padding: clamp(0.7rem, 1vw, 1rem) 0 !important;
    }

    .gg-checkout-inner .order-total td,
    .gg-checkout-inner .order-total strong,
    .gg-checkout-inner .order-total .amount {
        color: #2b2b2b !important;
        font-size: clamp(14px, 1vw, 20px) !important;
        font-weight: 500 !important;
    }

    .gg-checkout-inner #payment {
        background: transparent !important;
        border: 0 !important;
    }

    .gg-checkout-inner #payment ul.payment_methods {
        background: transparent !important;
        border: 0 !important;
        padding: 0 !important;
    }

    .gg-checkout-inner #payment div.payment_box {
        background: rgba(170,138,88,0.08) !important;
        color: #2b2b2b !important;
        border-radius: 0 !important;
        font-family: 'PT Serif', serif !important;
    }

    .gg-checkout-inner button.button,
    .gg-checkout-inner #place_order {
        width: 100%;
        padding: clamp(0.65rem, 1vw, 0.95rem) clamp(1rem, 2vw, 1.8rem) !important;

        background-color: #f1dfc4 !important;
        color: #3a2c1f !important;
        border: 2px solid #aa8a58 !important;
        border-radius: 0 !important;

        font-family: Georgia, "Times New Roman", serif !important;
        font-size: clamp(12px, 0.9vw, 16px) !important;
        text-transform: uppercase;
        letter-spacing: 0.08em;

        transition: all 0.25s ease;
    }

    .gg-checkout-inner button.button:hover,
    .gg-checkout-inner #place_order:hover {
        transform: translateY(-1px);
        border-color: #c4a26d !important;
        box-shadow: 0 4px 12px rgba(0,0,0,0.08);
    }

    @media (max-width: 900px) {
        .gg-checkout-inner form.checkout {
            grid-template-columns: 1fr;
        }

        .gg-checkout-inner #customer_details,
        .gg-checkout-inner #order_review_heading,
        .gg-checkout-inner #order_review {
            grid-column: 1;
        }
    }
			  
/* Checkout layout - rensad */

.gg-checkout-inner form.checkout {
    display: grid !important;
    grid-template-columns: minmax(0, 1.25fr) minmax(340px, 0.75fr);
    column-gap: clamp(3rem, 6vw, 7rem);
    align-items: start;
}

/* Vänster kolumn */
.gg-checkout-inner #customer_details {
    grid-column: 1;
    grid-row: 1;
    width: 100%;
    margin: 0 !important;
}

/* Höger kolumn */
.gg-checkout-inner #order_review_heading {
    grid-column: 2;
    grid-row: 1;
    margin: 0 0 clamp(1rem, 1.5vw, 1.5rem) !important;
}

.gg-checkout-inner #order_review {
    grid-column: 2;
    grid-row: 2;
    margin: 0 !important;
}

/* Ta bort WooCommerce floats */
.gg-checkout-inner #customer_details .col-1,
.gg-checkout-inner #customer_details .col-2 {
    float: none !important;
    width: 100% !important;
    margin: 0 !important;
}

/* Fältlayout */
.gg-checkout-inner .form-row {
    display: block !important;
    margin-bottom: clamp(0.8rem, 1.2vw, 1.4rem) !important;
}

.gg-checkout-inner .form-row label {
    display: block !important;
    margin-bottom: clamp(0.25rem, 0.4vw, 0.45rem) !important;
}

.gg-checkout-inner input.input-text,
.gg-checkout-inner textarea,
.gg-checkout-inner select,
.gg-checkout-inner .select2-container {
    width: 100% !important;
}

			  .gg-checkout-inner #order_review_heading {
    grid-column: 2;
    grid-row: 1;
}

.gg-checkout-inner #order_review {
    grid-column: 2;
    grid-row: 2;
}

.gg-checkout-inner #customer_details {
    grid-column: 1;
    grid-row: 1 / span 2;
}
			  
/* Labels */
.gg-checkout-inner .form-row label {
    margin: 0 !important;
    color: #B9965F !important;
    font-family: 'PT Serif', serif !important;
    font-size: clamp(11px, 0.8vw, 15px) !important;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    font-weight: 400 !important;
}

/* Inputs som linjer */
.gg-checkout-inner input.input-text,
.gg-checkout-inner textarea,
.gg-checkout-inner select,
.gg-checkout-inner .select2-container--default .select2-selection--single {
    width: 100% !important;

    background: transparent !important;
    background-color: transparent !important;

    border: 0 !important;
    border-bottom: 1px solid rgba(170,138,88,0.45) !important;
    border-radius: 0 !important;

    box-shadow: none !important;
    outline: none !important;

    color: #2b2b2b !important;
    font-family: 'PT Serif', serif !important;
    font-size: clamp(12px, 0.85vw, 16px) !important;
    letter-spacing: 0.04em;

    padding: clamp(0.35rem, 0.55vw, 0.6rem) 0 !important;
}

/* Fokus */
.gg-checkout-inner input.input-text:focus,
.gg-checkout-inner textarea:focus,
.gg-checkout-inner select:focus {
    border-bottom-color: #B9965F !important;
}

/* Placeholder */
.gg-checkout-inner input::placeholder,
.gg-checkout-inner textarea::placeholder {
    color: rgba(43,43,43,0.55) !important;
}

/* Select2 Sverige-fält */
.gg-checkout-inner .select2-container {
    width: 100% !important;
}

.gg-checkout-inner .select2-container .select2-selection--single {
    height: auto !important;
}

.gg-checkout-inner .select2-container--default .select2-selection--single .select2-selection__rendered {
    padding-left: 0 !important;
    color: #2b2b2b !important;
    line-height: 1.6 !important;
}
			  
			  
			  /* Själva dropdown-fältet */

.gg-checkout-inner select {
    background-color: #f4e6cd !important;
    color: #2b2b2b !important;

    border: 1px solid rgba(185,150,95,.45) !important;

    box-shadow:
        0 4px 12px rgba(0,0,0,.08),
        0 0 0 1px rgba(185,150,95,.15) !important;

    border-radius: 0 !important;
}

/* När man klickar i fältet */

.gg-checkout-inner select:focus {
    outline: none !important;

    border-color: #B9965F !important;

    box-shadow:
        0 8px 20px rgba(185,150,95,.25),
        0 0 0 2px rgba(185,150,95,.18) !important;
}

/* Förnamn/efternamn får ligga bredvid varandra */
.gg-checkout-inner #billing_first_name_field,
.gg-checkout-inner #billing_last_name_field {
    width: 100% !important;
    float: none !important;
}

/* Orderanteckningar */
.gg-checkout-inner .woocommerce-additional-fields {
    margin-top: clamp(1.5rem, 3vw, 3rem) !important;
}

.gg-checkout-inner textarea {
    min-height: clamp(4rem, 7vw, 7rem);
}

/* Betalningsbox */
.gg-checkout-inner #payment div.payment_box {
    background: transparent !important;
    background-color: transparent !important;
    border: 0 !important;
    box-shadow: none !important;
}

/* Mobil */
@media (max-width: 900px) {
    .gg-checkout-inner form.checkout {
        grid-template-columns: 1fr;
    }

    .gg-checkout-inner #customer_details,
    .gg-checkout-inner #order_review_heading,
    .gg-checkout-inner #order_review {
        grid-column: 1;
        grid-row: auto;
    }

    .gg-checkout-inner .form-row {
        grid-template-columns: 1fr;
        row-gap: 0.35rem;
    }
}			
			  
			  .gg-checkout-inner #order_review {
    margin-top: 0 !important;
}

.gg-checkout-inner #order_review table.shop_table {
    margin-top: 0 !important;
}

.gg-checkout-inner #order_review_heading {
    margin-bottom: clamp(0.7rem, 1vw, 1rem) !important;
}
			  
			  .gg-checkout-inner #order_review {
    transform: translateY(clamp(-4rem, -5vw, -2rem));
}
		
.gg-checkout-inner #order_review_heading {
    grid-column: 2;
    grid-row: 1;
    margin-bottom: 0 !important;
}

.gg-checkout-inner #order_review {
    grid-column: 2;
    grid-row: 1;

    padding-top: 5rem !important;
    margin-top: 3 !important;
}
	
			  
			  .select2-dropdown {
    background: #f1dfc4 !important;
    border: 1px solid rgba(185,150,95,.55) !important;
    box-shadow: 0 14px 35px rgba(0,0,0,.18) !important;
    border-radius: 0 !important;
}

.select2-results__option {
    font-family: 'PT Serif', serif !important;
    color: #2b2b2b !important;
    padding: 10px 14px !important;
}

.select2-results__option--highlighted,
.select2-container--default .select2-results__option--highlighted[aria-selected] {
    background: rgba(185,150,95,.25) !important;
    color: #2b2b2b !important;
}

.select2-container--default .select2-selection--single {
    background: transparent !important;
    border: 0 !important;
    border-bottom: 1px solid rgba(170,138,88,0.45) !important;
    border-radius: 0 !important;
}
		
			  
			  /* SelectWoo sökrutan */

.select2-search__field {
    background: transparent !important;
    background-color: transparent !important;

    border: 0 !important;
    border-bottom: 1px solid rgba(170,138,88,0.45) !important;
    border-radius: 0 !important;

    box-shadow: none !important;
    outline: none !important;

    color: #2b2b2b !important;
    font-family: 'PT Serif', serif !important;
}

/* Kortfält / Stripe */

.gg-checkout-inner #payment input,
.gg-checkout-inner #payment .wc-stripe-elements-field,
.gg-checkout-inner #payment .stripe-card-group,
.gg-checkout-inner #payment .StripeElement {
    background: transparent !important;
    background-color: transparent !important;

    border: 0 !important;
    border-bottom: 1px solid rgba(170,138,88,0.45) !important;
    border-radius: 0 !important;

    box-shadow: none !important;
}
	
			  
			  /* Produktbild i checkout orderöversikt */

.gg-checkout-product-line {
    display: inline-flex;
    align-items: center;
    gap: clamp(0.7rem, 1vw, 1rem);
}

.gg-checkout-product-thumb img {
    width: clamp(38px, 3.5vw, 58px);
    height: clamp(38px, 3.5vw, 58px);
    object-fit: cover;
    display: block;
}

.gg-checkout-product-name {
    display: inline-block;
}

/* Vita kortfält / betalningsfält */

.gg-checkout-inner #payment input,
.gg-checkout-inner #payment iframe,
.gg-checkout-inner #payment .wc-stripe-elements-field,
.gg-checkout-inner #payment .StripeElement,
.gg-checkout-inner #payment .stripe-card-group {
    background: transparent !important;
    background-color: transparent !important;
    border-radius: 0 !important;
    box-shadow: none !important;
}

.gg-checkout-inner #payment .wc-stripe-elements-field,
.gg-checkout-inner #payment .StripeElement {
    border: 0 !important;
    border-bottom: 1px solid rgba(170,138,88,0.45) !important;
}
	
			  /* Stripe / kortfält wrapper */

.gg-checkout-inner #payment .wc-stripe-elements-field,
.gg-checkout-inner #payment .StripeElement,
.gg-checkout-inner #payment .stripe-card-group,
.gg-checkout-inner #payment .wc-credit-card-form-card-number,
.gg-checkout-inner #payment .wc-credit-card-form-card-expiry,
.gg-checkout-inner #payment .wc-credit-card-form-card-cvc {
    background: transparent !important;
    background-color: transparent !important;

    border: 0 !important;
    border-bottom: 1px solid rgba(170,138,88,0.45) !important;
    border-radius: 0 !important;

    box-shadow: none !important;

    padding-left: 0 !important;
    padding-right: 0 !important;
}

/* Vanliga inputs i payment box */
.gg-checkout-inner #payment input[type="text"],
.gg-checkout-inner #payment input[type="tel"],
.gg-checkout-inner #payment input[type="email"] {
    background: transparent !important;
    background-color: transparent !important;

    border: 0 !important;
    border-bottom: 1px solid rgba(170,138,88,0.45) !important;
    border-radius: 0 !important;

    box-shadow: none !important;
    outline: none !important;
}

			  
			  
			  .gg-checkout-inner form.checkout {
    align-items: start !important;
}

.gg-checkout-express-slot {
    grid-column: 1;
    grid-row: 1;
    margin-bottom: clamp(1rem, 2vw, 2rem);
}

.gg-checkout-inner #customer_details {
    grid-column: 1;
    grid-row: 1;
    padding-top: clamp(4.5rem, 7vw, 7rem);
}

.gg-checkout-inner #order_review_heading {
    grid-column: 2;
    grid-row: 1;
}

.gg-checkout-inner #order_review {
    grid-column: 2;
    grid-row: 1;
    padding-top: 5rem !important;
}
			  
			  
@media(max-width:768px){
    .gg-checkout-page{
        width:100%;
        max-width:100%;
        padding:24px 4% 40px;
        margin-bottom:0;
        box-sizing:border-box;
        overflow:hidden;
    }

    .gg-checkout-inner{
        width:100%;
        max-width:100%;
        margin:0;
        transform:none !important;
        box-sizing:border-box;
    }

    .gg-checkout-inner form.checkout{
        display:block !important;
        width:100% !important;
        max-width:100% !important;
    }

    .gg-checkout-inner #customer_details,
    .gg-checkout-inner #order_review_heading,
    .gg-checkout-inner #order_review,
    .gg-checkout-express-slot{
        display:block !important;
        width:100% !important;
        max-width:100% !important;
        grid-column:auto !important;
        grid-row:auto !important;
        padding-top:0 !important;
        margin:0 0 28px !important;
        transform:none !important;
        box-sizing:border-box !important;
    }

    .gg-checkout-inner #customer_details .col-1,
    .gg-checkout-inner #customer_details .col-2{
        width:100% !important;
        float:none !important;
    }

    .gg-checkout-inner table.shop_table,
    .gg-checkout-inner #payment,
    .gg-checkout-inner .woocommerce-checkout-review-order,
    .gg-checkout-inner input,
    .gg-checkout-inner textarea,
    .gg-checkout-inner select,
    .gg-checkout-inner .select2-container,
    .gg-checkout-inner iframe,
    .gg-checkout-inner .StripeElement{
        width:100% !important;
        max-width:100% !important;
        box-sizing:border-box !important;
    }
}		  
			  
    </style>

			  
			  <script>
(function() {
    function ggInitCheckoutSelects() {
        if (!window.jQuery) return;

        const $ = window.jQuery;

        $('.gg-checkout-inner select').each(function() {
            const select = $(this);

            if (select.hasClass('select2-hidden-accessible')) return;

            if ($.fn.selectWoo) {
                select.selectWoo({
                    width: '100%'
                });
            } else if ($.fn.select2) {
                select.select2({
                    width: '100%'
                });
            }
        });
    }

    document.addEventListener('DOMContentLoaded', ggInitCheckoutSelects);

    if (window.jQuery) {
        window.jQuery(document.body).on('updated_checkout', ggInitCheckoutSelects);
    }
})();
</script>

			  <script>
(function() {
    function ggMoveExpressCheckout() {
        const form = document.querySelector('.gg-checkout-inner form.checkout');
        const customerDetails = document.querySelector('.gg-checkout-inner #customer_details');

        if (!form || !customerDetails) return;

        let slot = document.querySelector('.gg-checkout-express-slot');

        if (!slot) {
            slot = document.createElement('div');
            slot.className = 'gg-checkout-express-slot';
            form.insertBefore(slot, customerDetails);
        }

        const express = document.querySelector(
            '#wcpay-payment-request-wrapper, ' +
            '.wcpay-express-checkout-wrapper, ' +
            '#wc-stripe-payment-request-wrapper, ' +
            '.wc-stripe-payment-request-wrapper, ' +
            '.wc-stripe-banner-checkout, ' +
            '.wc-stripe-payment-request-button'
        );

        if (express && !slot.contains(express)) {
            slot.appendChild(express);
        }
    }

    document.addEventListener('DOMContentLoaded', ggMoveExpressCheckout);

    if (window.jQuery) {
        window.jQuery(document.body).on('updated_checkout', function() {
            setTimeout(ggMoveExpressCheckout, 300);
        });
    }

    setTimeout(ggMoveExpressCheckout, 700);
})();
</script>
			  
    <?php
    return ob_get_clean();
});

/**
 * Gold Goblins Footer
 */
add_action('init', function() {

    register_post_type('gg_newsletter', [
        'labels' => [
            'name'          => 'Nyhetsbrev',
            'singular_name' => 'Prenumerant',
            'menu_name'     => 'Nyhetsbrev',
            'add_new_item'  => 'Lägg till prenumerant',
            'edit_item'     => 'Redigera prenumerant',
        ],
        'public'       => false,
        'show_ui'      => true,
        'show_in_menu' => true,
        'supports'     => ['title'],
        'menu_icon'    => 'dashicons-email-alt',
    ]);

});


add_action('wp_ajax_gg_newsletter_signup', 'gg_handle_newsletter_signup');
add_action('wp_ajax_nopriv_gg_newsletter_signup', 'gg_handle_newsletter_signup');

function gg_handle_newsletter_signup() {

    if (
        empty($_POST['nonce']) ||
        !wp_verify_nonce(sanitize_text_field(wp_unslash($_POST['nonce'])), 'gg_newsletter_signup')
    ) {
        wp_send_json_error([
            'message' => 'Säkerhetskontrollen misslyckades. Ladda om sidan och försök igen.',
        ], 403);
    }

    if (!empty($_POST['website'])) {
        wp_send_json_success([
            'message' => 'Tack! Din anmälan är mottagen.',
        ]);
    }

    $email = isset($_POST['email'])
        ? sanitize_email(wp_unslash($_POST['email']))
        : '';

    if (!$email || !is_email($email)) {
        wp_send_json_error([
            'message' => 'Ange en giltig e-postadress.',
        ], 400);
    }

    $consent = !empty($_POST['consent']);

    if (!$consent) {
        wp_send_json_error([
            'message' => 'Du behöver godkänna att vi sparar din e-postadress för nyhetsbrev.',
        ], 400);
    }

    $existing = new WP_Query([
        'post_type'      => 'gg_newsletter',
        'post_status'    => ['private', 'publish'],
        'posts_per_page' => 1,
        'meta_query'     => [
            [
                'key'   => '_gg_newsletter_email',
                'value' => $email,
            ],
        ],
        'fields' => 'ids',
    ]);

   if ($existing->have_posts()) {
    wp_send_json_success([
        'message'       => 'Du finns redan med på listan. Tack!',
        'subscriber_id' => 0,
    ]);
}

    $post_id = wp_insert_post([
        'post_type'   => 'gg_newsletter',
        'post_status' => 'private',
        'post_title'  => $email,
    ], true);

    if (is_wp_error($post_id)) {
        wp_send_json_error([
            'message' => 'Något gick fel. Försök igen senare.',
        ], 500);
    }

    update_post_meta($post_id, '_gg_newsletter_email', $email);
    update_post_meta($post_id, '_gg_newsletter_consent', 'yes');
    update_post_meta($post_id, '_gg_newsletter_signup_date', current_time('mysql'));
    

    wp_send_json_success([
    'message'       => 'Tack! Du är nu anmäld till Gold Goblins nyhetsbrev.',
    'subscriber_id' => $post_id,
]);
}

add_action('wp_ajax_gg_newsletter_undo_signup', 'gg_handle_newsletter_undo_signup');
add_action('wp_ajax_nopriv_gg_newsletter_undo_signup', 'gg_handle_newsletter_undo_signup');

function gg_handle_newsletter_undo_signup() {

    if (
        empty($_POST['nonce']) ||
        !wp_verify_nonce(sanitize_text_field(wp_unslash($_POST['nonce'])), 'gg_newsletter_signup')
    ) {
        wp_send_json_error([
            'message' => 'Säkerhetskontrollen misslyckades. Ladda om sidan och försök igen.',
        ], 403);
    }

    $subscriber_id = isset($_POST['subscriber_id'])
        ? absint($_POST['subscriber_id'])
        : 0;

    if (!$subscriber_id) {
        wp_send_json_error([
            'message' => 'Kunde inte hitta anmälan att ångra.',
        ], 400);
    }

    $post = get_post($subscriber_id);

    if (!$post || $post->post_type !== 'gg_newsletter') {
        wp_send_json_error([
            'message' => 'Anmälan finns inte längre.',
        ], 404);
    }

    wp_delete_post($subscriber_id, true);

    wp_send_json_success([
        'message' => 'Din anmälan har ångrats.',
    ]);
}

add_shortcode('gg_footer', function() {
    ob_start();
    ?>

<section class="gg-footer">

    <div class="gg-footer-col gg-newsletter">
        <div class="gg-footer-title">BLI EN GOBLIN</div>
        <p>FÅ EXKLUSIVA ERBJUDANDEN,<br>KAMPANJER &amp; NYHETSBREV.</p>

        <form class="gg-email-form" action="#" method="post">
    <label class="gg-email-label" for="gg-footer-email">Email</label>

    <div class="gg-email-box">
        <input
            id="gg-footer-email"
            type="email"
            name="email"
            placeholder="EMAIL"
            autocomplete="email"
            required
        >

        <input
            type="text"
            name="website"
            class="gg-newsletter-website"
            tabindex="-1"
            autocomplete="off"
            aria-hidden="true"
        >

        <input
            type="hidden"
            name="gg_newsletter_nonce"
            value="<?php echo esc_attr(wp_create_nonce('gg_newsletter_signup')); ?>"
        >

        <button type="submit" aria-label="Prenumerera">→</button>
    </div>

    <label class="gg-newsletter-consent">
        <input type="checkbox" name="consent" value="1" required>
        <span>
    Jag samtycker till att Gold Goblins sparar min e-postadress för nyhetsbrev och erbjudanden.
    <a href="/integritetspolicy/">Läs mer om hur vi hanterar personuppgifter.</a>
</span>
    </label>

    <p class="gg-newsletter-message" aria-live="polite"></p>
</form>
    </div>

    <div class="gg-footer-col">
        <div class="gg-footer-title">KOLLEKTIONER</div>
        <a href="https://www.goldgoblins.se/ringar/">RINGAR</a>
        <a href="https://www.goldgoblins.se/halsband/">HALSBAND</a>
        <a href="https://www.goldgoblins.se/armband/">ARMBAND</a>
        <a href="https://www.goldgoblins.se/hangsmycke/">HÄNGSMYCKE</a>
		<a href="https://www.goldgoblins.se/design/">DESIGNA EGET SMYCKE</a>
    </div>

    <div class="gg-footer-col">
        <div class="gg-footer-title">VERKSTADEN</div>
        <a href="https://www.goldgoblins.se/var-verksamhet/">VÅR VERKSAMHET</a>
        <a href="https://www.goldgoblins.se/vardering/">VÄRDERING</a>
        <a href="https://www.goldgoblins.se/kontakta-oss/">KONTAKTA OSS</a>
		<a href="https://www.goldgoblins.se/guld/">GULDPRIS</a>
		<a href="https://www.goldgoblins.se/silver/">SILVERPRIS</a>
		<a href="https://www.goldgoblins.se/blog/">BLOG</a>
    </div>

    <div class="gg-footer-col">
        <div class="gg-footer-title">KUNDSERVICE</div>
        <a href="https://www.goldgoblins.se/kontakta-oss/#faq">FAQ</a>
        <a href="https://www.goldgoblins.se/kontakta-oss/#leverans">FRAKT &amp; LEVERANS</a>
        <a href="https://www.goldgoblins.se/kontakta-oss/#retur">RETUR</a>
        <a href="https://www.goldgoblins.se/kontakta-oss/#reklamation">REKLAMATION</a>
        <a href="https://www.goldgoblins.se/kontakta-oss/#kontaktformular">KONTAKTA OSS</a>
		<a href="https://www.goldgoblins.se/integritetspolicy/">INTEGRITETSPOLICY</a>
    </div>

   <div class="gg-footer-col">
    <div class="gg-footer-title">GOLD GOBLINS</div>
    <p>ORG.NR: 969799-8897</p>
    <p>BG: 360-1051</p>
    <p>LIDKÖPING</p>
    <p>SVERIGE</p>

    <div class="gg-footer-socials" aria-label="Gold Goblins på sociala medier">
        <a 
            href="https://www.facebook.com/profile.php?id=61591345509158" 
            class="gg-footer-social-link" 
            target="_blank" 
            rel="noopener noreferrer" 
            aria-label="Besök Gold Goblins på Facebook"
        >
            <svg viewBox="0 0 24 24" aria-hidden="true">
                <path d="M14.2 8.1V6.6c0-.7.5-.9.9-.9h2.1V2.2L14.3 2c-3.2 0-4.9 1.9-4.9 5.3v.8H6.8v3.8h2.6V22h4.1V11.9h3.1l.5-3.8h-3z"/>
            </svg>
        </a>

        <a 
            href="https://www.instagram.com/gold_goblins/" 
            class="gg-footer-social-link" 
            target="_blank" 
            rel="noopener noreferrer" 
            aria-label="Besök Gold Goblins på Instagram"
        >
            <svg viewBox="0 0 24 24" aria-hidden="true">
                <path d="M7.5 2h9A5.5 5.5 0 0 1 22 7.5v9a5.5 5.5 0 0 1-5.5 5.5h-9A5.5 5.5 0 0 1 2 16.5v-9A5.5 5.5 0 0 1 7.5 2zm0 2A3.5 3.5 0 0 0 4 7.5v9A3.5 3.5 0 0 0 7.5 20h9a3.5 3.5 0 0 0 3.5-3.5v-9A3.5 3.5 0 0 0 16.5 4h-9zm4.5 3.4A4.6 4.6 0 1 1 7.4 12 4.6 4.6 0 0 1 12 7.4zm0 2A2.6 2.6 0 1 0 14.6 12 2.6 2.6 0 0 0 12 9.4zm4.85-2.55a1.05 1.05 0 1 1-1.05 1.05 1.05 1.05 0 0 1 1.05-1.05z"/>
            </svg>
        </a>
    </div>
</div>

</section>

<div class="gg-newsletter-modal-overlay" aria-hidden="true"></div>

<div class="gg-newsletter-modal" aria-hidden="true">
    <button type="button" class="gg-newsletter-close" aria-label="Stäng">×</button>
    <div class="gg-newsletter-title">TACK!</div>
<p class="gg-newsletter-modal-message">Du är nu anmäld till Gold Goblins nyhetsbrev.</p>
<button type="button" class="gg-newsletter-undo">Ångra</button>
</div>

<style>
.gg-footer{
    width:100%;
    display:grid;
    grid-template-columns:1.3fr 1fr 1fr 1fr 1fr;
    gap:clamp(25px, 4vw, 70px);
    padding:clamp(40px, 5vw, 90px) 8%;
    box-sizing:border-box;
    background-image:url("https://www.goldgoblins.se/wp-content/uploads/2026/06/Gold_Goblins_marmor.webp");
    background-size:cover;
    background-position:center;
}

.gg-footer-col{
    display:flex;
    flex-direction:column;
    gap:clamp(8px, 0.8vw, 14px);
}

.gg-footer-title{
    color:#B9965F;
    font-family:'PT Serif', serif;
    font-size:clamp(15px, 1.1vw, 22px);
    letter-spacing:0.25em;
    margin:0 0 clamp(10px, 1vw, 20px);
}

.gg-footer p,
.gg-footer a{
    color:#f4f1ec;
    font-family:'PT Serif', serif;
    font-size:clamp(12px, 0.85vw, 17px);
    line-height:1.6;
    text-decoration:none;
    margin:0;
    letter-spacing:0.05em;
}
	
	.gg-footer a{
    transition:color 0.25s ease;
}

.gg-footer a:hover{
    color:#B9965F;
}

	.gg-footer-socials{
    display:flex;
    align-items:center;
    gap:clamp(10px, 0.8vw, 16px);
    margin-top:clamp(8px, 0.8vw, 14px);
}

.gg-footer .gg-footer-social-link{
    width:clamp(14px, 1.8vw, 24px);
    height:clamp(14px, 1.8vw, 24px);
    display:inline-flex;
    align-items:center;
    justify-content:center;
    color:#B9965F;
    transition:
        color 0.25s ease,
        transform 0.25s ease;
}

.gg-footer .gg-footer-social-link svg{
    width:100%;
    height:100%;
    display:block;
    fill:currentColor;
}

.gg-footer .gg-footer-social-link:hover{
    color:#f4f1ec;
    transform:translateY(-1px);
}
	
.gg-email-form{
    margin-top:clamp(10px, 1vw, 20px);
    width:100%;
    max-width:320px;
}

.gg-email-label{
    position:absolute;
    width:1px;
    height:1px;
    overflow:hidden;
    clip:rect(0, 0, 0, 0);
}

.gg-email-box{
    border:1px solid #9F8560;
    display:flex;
    justify-content:space-between;
    align-items:center;
    width:100%;
    min-height:44px;
    box-sizing:border-box;
}

.gg-email-box input{
    flex:1;
    min-width:0;
    background:transparent;
    border:0;
    outline:0;
    color:#f4f1ec;
    padding:clamp(10px, 0.8vw, 14px) clamp(12px, 1vw, 18px);
    font-family:'PT Serif', serif;
    font-size:clamp(12px, 0.85vw, 16px);
    letter-spacing:0.1em;
    text-transform:uppercase;
}

.gg-email-box input::placeholder{
    color:#B9965F;
    opacity:1;
}

.gg-email-box button{
    background:transparent;
    border:0;
    color:#B9965F;
    cursor:pointer;
    padding:0 clamp(12px, 1vw, 18px);
    font-family:'PT Serif', serif;
    font-size:clamp(18px, 1.2vw, 24px);
}

.gg-newsletter-modal-overlay{
    position:fixed;
    inset:0;
    background:rgba(0,0,0,0.45);
    opacity:0;
    visibility:hidden;
    transition:opacity 0.25s ease, visibility 0.25s ease;
    z-index:9998;
}

.gg-newsletter-modal{
    position:fixed;
    left:50%;
    top:50%;
    transform:translate(-50%, -50%) scale(0.94);
    width:min(90vw, 380px);
    min-height:220px;
    background:#f1dfc4;
    border:2px solid #9F8560;
    box-shadow:0 20px 50px rgba(0,0,0,0.35);
    padding:2rem;
    box-sizing:border-box;
    text-align:center;
    opacity:0;
    visibility:hidden;
    transition:opacity 0.25s ease, visibility 0.25s ease, transform 0.25s ease;
    z-index:9999;
}

.gg-newsletter-modal.is-open{
    opacity:1;
    visibility:visible;
    transform:translate(-50%, -50%) scale(1);
}

.gg-newsletter-modal-overlay.is-open{
    opacity:1;
    visibility:visible;
}

.gg-newsletter-title{
    color:#9F8560;
    margin:0 0 1rem;
    font-family:'PT Serif', serif;
    font-size:clamp(18px, 1.4vw, 26px);
    letter-spacing:0.18em;
}

.gg-newsletter-modal p{
    color:#2f2b25;
    font-family:'PT Serif', serif;
    line-height:1.6;
}

.gg-newsletter-close{
    position:absolute;
    top:0.7rem;
    right:0.9rem;
    background:none;
    border:0;
    color:#9F8560;
    font-size:1.8rem;
    cursor:pointer;
}

.gg-newsletter-undo{
    position:absolute;
    bottom:18px;
    left:22px;
    margin:0;
    padding:0;
    background:none;
    border:0;
    color:#9F8560 !important;
    cursor:pointer;
    text-decoration:underline;
    font-family:'PT Serif', serif;
    font-size:13px;
}

.gg-newsletter-undo[disabled]{
    opacity:0.55;
    cursor:wait;
}
	
	.gg-newsletter-website{
    position:absolute;
    left:-9999px;
    width:1px;
    height:1px;
    opacity:0;
    pointer-events:none;
}

.gg-newsletter-consent{
    display:flex;
    align-items:flex-start;
    gap:8px;
    margin-top:12px;
    color:#f4f1ec;
    font-family:'PT Serif', serif;
    font-size:clamp(11px, 0.75vw, 14px);
    line-height:1.5;
    letter-spacing:0.03em;
    cursor:pointer;
}

.gg-newsletter-consent input{
    margin-top:4px;
    accent-color:#B9965F;
}

.gg-newsletter-message{
    margin-top:10px !important;
    color:#B9965F !important;
    font-size:clamp(11px, 0.75vw, 14px) !important;
    line-height:1.5 !important;
}

.gg-newsletter-message.is-error{
    color:#f1b6a8 !important;
}

.gg-email-box button[disabled]{
    opacity:0.55;
    cursor:wait;
}

@media(max-width:1100px){
    .gg-footer{
        grid-template-columns:1.4fr 1fr 1fr;
    }

    .gg-newsletter{
        grid-column:1 / -1;
    }
}

@media(max-width:700px){
    .gg-footer{
        grid-template-columns:1fr;
        padding:45px 7%;
        gap:32px;
    }

    .gg-email-form{
        max-width:100%;
    }
}
</style>

<script>
const ggNewsletterAjaxUrl = <?php echo wp_json_encode(admin_url('admin-ajax.php')); ?>;
let ggNewsletterLastSubscriberId = 0;
let ggNewsletterLastNonce = '';

document.addEventListener('submit', function(e) {
    const form = e.target.closest('.gg-email-form');
    if (!form) return;

    e.preventDefault();

    const emailInput = form.querySelector('input[type="email"]');
    const consentInput = form.querySelector('input[name="consent"]');
    const nonceInput = form.querySelector('input[name="gg_newsletter_nonce"]');
    const websiteInput = form.querySelector('input[name="website"]');
    const message = form.querySelector('.gg-newsletter-message');
    const button = form.querySelector('button[type="submit"]');

    if (!emailInput || !emailInput.checkValidity()) {
        emailInput.reportValidity();
        return;
    }

    if (!consentInput || !consentInput.checked) {
        consentInput.reportValidity();
        return;
    }

    if (message) {
        message.textContent = '';
        message.classList.remove('is-error');
    }

    if (button) {
        button.disabled = true;
        button.textContent = '…';
    }

    const nonce = nonceInput ? nonceInput.value : '';

    const formData = new FormData();
    formData.append('action', 'gg_newsletter_signup');
    formData.append('email', emailInput.value);
    formData.append('consent', consentInput.checked ? '1' : '');
    formData.append('nonce', nonce);
    formData.append('website', websiteInput ? websiteInput.value : '');

    fetch(ggNewsletterAjaxUrl, {
        method: 'POST',
        body: formData,
        credentials: 'same-origin'
    })
    .then(function(response) {
        return response.json();
    })
    .then(function(data) {
        const modal = document.querySelector('.gg-newsletter-modal');
        const overlay = document.querySelector('.gg-newsletter-modal-overlay');
        const modalMessage = document.querySelector('.gg-newsletter-modal-message');
        const undoBtn = document.querySelector('.gg-newsletter-undo');

        if (!data || !data.success) {
            throw new Error(data && data.data && data.data.message ? data.data.message : 'Något gick fel.');
        }

        ggNewsletterLastSubscriberId = data.data && data.data.subscriber_id ? parseInt(data.data.subscriber_id, 10) : 0;
        ggNewsletterLastNonce = nonce;

        if (modalMessage && data.data && data.data.message) {
            modalMessage.textContent = data.data.message;
        }

        if (undoBtn) {
            undoBtn.style.display = ggNewsletterLastSubscriberId ? 'block' : 'none';
            undoBtn.disabled = false;
            undoBtn.textContent = 'Ångra';
        }

        if (modal && overlay) {
            modal.classList.add('is-open');
            overlay.classList.add('is-open');
        }

        form.reset();
    })
    .catch(function(error) {
        if (message) {
            message.textContent = error.message;
            message.classList.add('is-error');
        }
    })
    .finally(function() {
        if (button) {
            button.disabled = false;
            button.textContent = '→';
        }
    });
});

document.addEventListener('click', function(e) {
    const undoBtn = e.target.closest('.gg-newsletter-undo');
    const closeBtn = e.target.closest('.gg-newsletter-close');
    const overlay = e.target.closest('.gg-newsletter-modal-overlay');

    const modal = document.querySelector('.gg-newsletter-modal');
    const modalOverlay = document.querySelector('.gg-newsletter-modal-overlay');
    const modalMessage = document.querySelector('.gg-newsletter-modal-message');
    const emailInput = document.querySelector('.gg-email-form input[type="email"]');

    if (undoBtn) {
        e.preventDefault();

        if (!ggNewsletterLastSubscriberId) {
            if (modal) {
                modal.classList.remove('is-open');
            }

            if (modalOverlay) {
                modalOverlay.classList.remove('is-open');
            }

            return;
        }

        undoBtn.disabled = true;
        undoBtn.textContent = 'Ångrar…';

        const formData = new FormData();
        formData.append('action', 'gg_newsletter_undo_signup');
        formData.append('subscriber_id', ggNewsletterLastSubscriberId);
        formData.append('nonce', ggNewsletterLastNonce);

        fetch(ggNewsletterAjaxUrl, {
            method: 'POST',
            body: formData,
            credentials: 'same-origin'
        })
        .then(function(response) {
            return response.json();
        })
        .then(function(data) {
            if (!data || !data.success) {
                throw new Error(data && data.data && data.data.message ? data.data.message : 'Kunde inte ångra anmälan.');
            }

            ggNewsletterLastSubscriberId = 0;
            ggNewsletterLastNonce = '';

            if (modalMessage) {
                modalMessage.textContent = data.data && data.data.message ? data.data.message : 'Din anmälan har ångrats.';
            }

            undoBtn.textContent = 'Ångrat';
            undoBtn.style.display = 'none';

            window.setTimeout(function() {
                if (modal) {
                    modal.classList.remove('is-open');
                }

                if (modalOverlay) {
                    modalOverlay.classList.remove('is-open');
                }

                if (emailInput) {
                    emailInput.focus();
                }
            }, 1200);
        })
        .catch(function(error) {
            if (modalMessage) {
                modalMessage.textContent = error.message;
            }

            undoBtn.disabled = false;
            undoBtn.textContent = 'Ångra';
        });

        return;
    }

    if (!closeBtn && !overlay) return;

    if (modal) {
        modal.classList.remove('is-open');
    }

    if (modalOverlay) {
        modalOverlay.classList.remove('is-open');
    }
});
</script>

    <?php
    return ob_get_clean();
});

/**
 * Gold Goblins Banner
 */
add_shortcode('gg_banner', function() {
    ob_start();
    ?>

<section class="gg-benefits">

    <div class="gg-benefit">
        <img src="https://www.goldgoblins.se/wp-content/uploads/2026/06/Gold_Goblins_lilja.webp" alt="" loading="lazy" decoding="async">
        <div>SVENSKT<br>HANTVERK</div>
    </div>

    <img class="gg-divider" src="https://www.goldgoblins.se/wp-content/uploads/2026/06/Gold_Goblins_skiljare_1.webp" alt="" loading="lazy" decoding="async">

    <div class="gg-benefit">
        <img src="https://www.goldgoblins.se/wp-content/uploads/2026/06/Gold_Goblins_logga_3.webp" alt="" loading="lazy" decoding="async">
        <div>LIVSLÅNG<br>HANTVERKSGARANTI</div>
    </div>

    <img class="gg-divider" src="https://www.goldgoblins.se/wp-content/uploads/2026/06/Gold_Goblins_skiljare_2.webp" alt="" loading="lazy" decoding="async">

    <div class="gg-benefit">
        <img src="https://www.goldgoblins.se/wp-content/uploads/2026/06/Gold_Goblins_skold.webp" alt="" loading="lazy" decoding="async">
        <div>SÄKER &amp; FÖRSÄKRAD<br>FRAKT</div>
    </div>

    <img class="gg-divider" src="https://www.goldgoblins.se/wp-content/uploads/2026/06/Gold_Goblins_skiljare_1.webp" alt="" loading="lazy" decoding="async">

    <div class="gg-benefit">
        <img src="https://www.goldgoblins.se/wp-content/uploads/2026/06/Gold_Goblins_30.webp" alt="" loading="lazy" decoding="async">
        <div>30 DAGARS<br>RETURRÄTT</div>
    </div>

    <img class="gg-divider" src="https://www.goldgoblins.se/wp-content/uploads/2026/06/Gold_Goblins_skiljare_2.webp" alt="" loading="lazy" decoding="async">

    <div class="gg-benefit">
        <img src="https://www.goldgoblins.se/wp-content/uploads/2026/06/Gold_Goblins_paket.webp" alt="" loading="lazy" decoding="async">
        <div>ELEGANT<br>FÖRPACKNING</div>
    </div>

</section>

<style>
.gg-benefits{
    position:relative;

    width:100%;
    display:grid;
    grid-template-columns:
        1fr auto
        1fr auto
        1fr auto
        1fr auto
        1fr;

    border-top:0;
    border-bottom:0;

    align-items:center;

    background-color:#f1dfc4;
    background-image:
        radial-gradient(circle at 20% 15%, rgba(255,255,255,0.10), transparent 30%),
        radial-gradient(circle at 80% 35%, rgba(120,90,55,0.03), transparent 35%),
        radial-gradient(circle at 45% 80%, rgba(255,255,255,0.06), transparent 30%),
        linear-gradient(135deg, rgba(255,255,255,0.03), rgba(120,90,55,0.02));
    background-size:cover;
    background-position:center;

    padding:clamp(25px,3vw,60px) 5%;
    box-sizing:border-box;
}

	.gg-benefits::before,
.gg-benefits::after{
    content:"";
    position:absolute;
    left:0;
    right:0;

    height:1px;

    background:linear-gradient(
        90deg,
        transparent 0%,
        rgba(159,133,96,0.28) 18%,
        rgba(159,133,96,0.70) 50%,
        rgba(159,133,96,0.28) 82%,
        transparent 100%
    );

    pointer-events:none;
}

.gg-benefits::before{
    top:0;
}

.gg-benefits::after{
    bottom:0;
}
	
.gg-benefit{
    display:flex;
    flex-direction:column;
    align-items:center;
    text-align:center;
}

.gg-benefit img{
    width:clamp(70px,6vw,140px);
    height:auto;
    margin-bottom:clamp(15px,1.5vw,25px);
}

.gg-benefit div{
    font-family:'PT Serif', serif;
    color:#2f2b25;
    font-size:clamp(14px,1.2vw,28px);
    line-height:1.4;
    letter-spacing:0.05em;
}

.gg-divider{
    height:clamp(180px,14vw,320px);
    width:auto;
    display:block;
}
	
	
@media(max-width:768px){

    .gg-benefits{
        width:100%;
        max-width:100%;
        padding:18px 4%;
        box-sizing:border-box;
        gap:0;
        grid-template-columns:
            minmax(0,1fr) 6px
            minmax(0,1fr) 6px
            minmax(0,1fr) 6px
            minmax(0,1fr) 6px
            minmax(0,1fr);
    }

    .gg-benefit{
        min-width:0;
    }

    .gg-benefit img{
        width:38px;
        margin-bottom:8px;
    }

    .gg-benefit div{
        font-size:7px;
        line-height:1.2;
        letter-spacing:0.01em;
    }

    .gg-divider{
        width:6px;
        height:60px;
        object-fit:contain;
    }
}
	
	
</style>

    <?php
    return ob_get_clean();
});

/**
 * Gold Goblins Slider
 */
add_shortcode('gg_slider', function() {
    ob_start();

    $slides = [
        ['url' => '/hangsmycke', 'id' => 1326],
        ['url' => '/ringar',    'id' => 1191],
        ['url' => '/ringar',    'id' => 1186],
        ['url' => '/halsband',  'id' => 1344],
        ['url' => '/ringar',    'id' => 1333],
        ['url' => '/armband',   'id' => 1342],
        ['url' => '/ringar',    'id' => 1336],
    ];
    ?>

    <div class="gg-slider">
        <?php foreach ($slides as $slide) : ?>
            <a href="<?php echo esc_url($slide['url']); ?>">
                <?php echo wp_get_attachment_image($slide['id'], 'thumbnail', false, [
                    'loading'  => 'lazy',
                    'decoding' => 'async',
                    'sizes'    => '(max-width: 600px) 45vw, (max-width: 900px) 25vw, 14vw',
                ]); ?>
            </a>
        <?php endforeach; ?>
    </div>

    <style>
 .gg-slider{
    position:relative;
    display:flex;
    width:100%;
    gap:10px;
    padding:20px 2%;
    box-sizing:border-box;

    border-top:0;
    border-bottom:0;

    background-color:#f1dfc4;
    background-image:
        radial-gradient(circle at 20% 15%, rgba(255,255,255,0.10), transparent 30%),
        radial-gradient(circle at 80% 35%, rgba(120,90,55,0.03), transparent 35%),
        radial-gradient(circle at 45% 80%, rgba(255,255,255,0.06), transparent 30%),
        linear-gradient(135deg, rgba(255,255,255,0.03), rgba(120,90,55,0.02));
    background-size:cover;
    background-position:center;
}

	.gg-slider::before,
.gg-slider::after{
    content:"";
    position:absolute;
    left:0;
    right:0;

    height:1px;

    background:linear-gradient(
        90deg,
        transparent 0%,
        rgba(159,133,96,0.28) 18%,
        rgba(159,133,96,0.70) 50%,
        rgba(159,133,96,0.28) 82%,
        transparent 100%
    );

    pointer-events:none;
}

.gg-slider::before{
    top:0;
}

.gg-slider::after{
    bottom:0;
}
	
    .gg-slider a{
        flex:1;
        min-width:0;
        display:block;
    }

    .gg-slider img{
        width:100%;
        height:auto;
        aspect-ratio:1/1;
        object-fit:cover;
        border-radius:4px;
        display:block;
    }
    </style>

    <?php
    return ob_get_clean();
});

/**
 * Gold Goblins Verkstad(craft)
 */
add_shortcode('gg_craft', function() {
    ob_start();

    $features = [
        [
            'id'    => 1641,
            'label' => 'ÄKTA<br>ÄDELMETALLER',
        ],
        [
            'id'    => 1640,
            'label' => 'ÅTERVUNNET<br>GULD &amp; SILVER',
        ],
        [
            'id'    => 1639,
            'label' => 'SVENSKT<br>HANTVERK',
        ],
        [
            'id'    => 1638,
            'label' => 'SKAPAT FÖR<br>GENERATIONER',
        ],
    ];
    ?>

<section class="gg-craft-section">

    <div class="gg-craft-left">

        <h2 class="gg-small-title">VERKSTADEN</h2>

        <img
            class="gg-small-arrow"
            src="https://www.goldgoblins.se/wp-content/uploads/2026/06/e01we3r5y6tyjggretgh-1.webp"
            alt=""
            loading="lazy"
            decoding="async"
        >

        <p>
            I vår smyckesverkstad i Lidköping skapar vi smycken där traditionellt hantverk möter modern formgivning. Vi arbetar med nytillverkning, specialbeställningar och återbruk av ädelmetaller för att ge varje smycke en genomtänkt form, hög kvalitet och en känsla som kan bäras länge.
        </p>

        <a href="/var-verksamhet/" class="gg-text-link">VÅR VERKSAMHET →</a>

    </div>

    <div class="gg-craft-center">
        <?php
        echo wp_get_attachment_image(
            1235,
            'medium_large',
            false,
            [
                'class'    => 'gg-craft-image',
                'loading'  => 'lazy',
                'decoding' => 'async',
                'alt'      => '',
                'sizes'    => '(max-width: 768px) 100vw, 28vw',
            ]
        );
        ?>
    </div>

    <div class="gg-craft-right">

        <?php foreach ($features as $feature) : ?>
            <div class="gg-feature">

                <span class="gg-feature-icon">
                    <?php
                    echo wp_get_attachment_image(
                        $feature['id'],
                        'medium',
                        false,
                        [
                            'class'    => 'gg-craft-icon',
                            'loading'  => 'lazy',
                            'decoding' => 'async',
                            'alt'      => '',
                            'sizes'    => '(max-width: 768px) 44px, 72px',
                        ]
                    );
                    ?>
                </span>

                <span class="gg-feature-text">
                    <?php echo wp_kses($feature['label'], ['br' => []]); ?>
                </span>

            </div>
        <?php endforeach; ?>

    </div>

</section>

<style>
.gg-craft-section{
    position:relative;
    isolation:isolate;

    width:100%;
    display:grid;
    grid-template-columns:minmax(0, 34%) minmax(260px, 28%) minmax(0, 38%);

    min-height:clamp(360px, 30vw, 520px);

    background-image:
        linear-gradient(rgba(35,35,32,0.08), rgba(35,35,32,0.08)),
        url("https://www.goldgoblins.se/wp-content/uploads/2026/06/Gold_Goblins_marmor.webp");
    background-size:cover;
    background-position:center;

    box-sizing:border-box;
    border-top:0;
    border-bottom:0;
    overflow:hidden;
}

.gg-craft-section::before,
.gg-craft-section::after{
    content:"";
    position:absolute;
    left:0;
    right:0;

    height:1px;

    background:linear-gradient(
        90deg,
        transparent 0%,
        rgba(159,133,96,0.28) 18%,
        rgba(159,133,96,0.70) 50%,
        rgba(159,133,96,0.28) 82%,
        transparent 100%
    );

    pointer-events:none;
    z-index:5;
}

.gg-craft-section::before{
    top:0;
}

.gg-craft-section::after{
    bottom:0;
}

.gg-craft-left{
    padding:clamp(28px, 3.2vw, 58px) clamp(30px, 4vw, 70px);
    box-sizing:border-box;

    display:flex;
    flex-direction:column;
    justify-content:center;
}

.gg-craft-section .gg-small-title{
    color:#B9965F;
    font-family:'PT Serif', serif;
    font-size:clamp(30px, 2.25vw, 44px);
    line-height:1.15;
    letter-spacing:0.15em;
    font-weight:400;
    margin:0 0 clamp(14px, 1.6vw, 28px);
}

.gg-craft-section .gg-small-arrow{
    width:clamp(70px, 6vw, 115px);
    height:auto;
    margin-bottom:clamp(18px, 2vw, 34px);
}

.gg-craft-left p{
    color:#f4f1ec;
    font-family:'PT Serif', serif;
    letter-spacing:0.13em;
    font-size:clamp(14px, 1.05vw, 18px);
    line-height:1.65;
    margin:0 0 clamp(22px, 2.2vw, 36px);
    max-width:34em;
}

.gg-text-link{
    position:relative;
    display:inline-block;
    width:fit-content;

    color:#B9965F;
    text-decoration:none;
    font-family:'PT Serif', serif;
    font-size:clamp(14px, 1.25vw, 18px);
    letter-spacing:0.2em;

    z-index:1;
    transition:color 0.25s ease;
}

.gg-text-link::before{
    content:"";
    position:absolute;
    left:50%;
    top:50%;

    width:calc(100% + 12px);
    height:1.4em;

    transform:translate(-50%, -50%) scale(0.7);

    background:radial-gradient(
        ellipse at center,
        rgba(255,255,255,0.18) 0%,
        rgba(255,255,255,0.06) 50%,
        rgba(255,255,255,0) 100%
    );

    border-radius:999px;
    filter:blur(4px);

    opacity:0;
    transition:
        opacity 0.25s ease,
        transform 0.25s ease;

    pointer-events:none;
    z-index:-1;
}

.gg-text-link:hover::before{
    opacity:1;
    transform:translate(-50%, -50%) scale(1);
}

.gg-craft-center{
    position:relative;
    height:100%;
    min-height:100%;
}

.gg-craft-center::before,
.gg-craft-center::after{
    content:"";
    position:absolute;
    top:0;
    bottom:0;

    width:1px;

    background:linear-gradient(
        180deg,
        transparent 0%,
        rgba(159,133,96,0.28) 18%,
        rgba(159,133,96,0.70) 50%,
        rgba(159,133,96,0.28) 82%,
        transparent 100%
    );

    pointer-events:none;
    z-index:3;
}

.gg-craft-center::before{
    left:0;
}

.gg-craft-center::after{
    right:0;
}

.gg-craft-center img{
    width:100%;
    height:100%;
    object-fit:cover;
    object-position:center;
    display:block;
    border:0;
    box-sizing:border-box;
}

.gg-craft-right{
    display:flex;
    flex-direction:column;
    justify-content:center;
    align-items:center;

    gap:clamp(18px, 2.2vw, 38px);
    padding:clamp(28px, 3.2vw, 54px);
    box-sizing:border-box;
}

.gg-feature{
    display:grid;
    grid-template-columns:clamp(46px, 4vw, 72px) minmax(0, 1fr);
    align-items:center;
    gap:clamp(18px, 2vw, 34px);

    width:min(100%, 430px);
}

.gg-feature-icon{
    width:clamp(46px, 4vw, 72px);
    height:clamp(46px, 4vw, 72px);

    display:flex;
    align-items:center;
    justify-content:center;
}

.gg-feature-icon img{
    width:100%;
    height:100%;
    object-fit:contain;
    object-position:center;
    display:block;
}

.gg-feature-text{
    color:#B9965F;
    font-family:'PT Serif', serif;
    font-size:clamp(16px, 1.45vw, 27px);
    line-height:1.45;
    letter-spacing:0.22em;
    font-weight:400;
}

@media(max-width:900px){
    .gg-craft-section{
        grid-template-columns:1fr;
        min-height:unset;
        width:100vw;
        max-width:100vw;
        margin-left:calc(50% - 50vw);
        margin-right:calc(50% - 50vw);
        background-size:cover;
        background-position:center;
    }

    .gg-craft-left{
        padding:42px 7% 34px;
    }

    .gg-craft-section .gg-small-title{
        font-size:clamp(32px, 9vw, 44px);
        letter-spacing:0.14em;
    }

    .gg-craft-section .gg-small-arrow{
        width:100px;
        margin-bottom:28px;
    }

    .gg-craft-left p{
        font-size:15px;
        line-height:1.65;
        letter-spacing:0.07em;
        margin-bottom:28px;
        max-width:none;
    }

    .gg-text-link{
        font-size:14px;
        letter-spacing:0.14em;
    }

    .gg-craft-center{
        height:auto;
        min-height:unset;
    }

    .gg-craft-center::before,
    .gg-craft-center::after{
        left:0;
        right:0;
        width:auto;
        height:1px;

        background:linear-gradient(
            90deg,
            transparent 0%,
            rgba(159,133,96,0.28) 18%,
            rgba(159,133,96,0.70) 50%,
            rgba(159,133,96,0.28) 82%,
            transparent 100%
        );
    }

    .gg-craft-center::before{
        top:0;
        bottom:auto;
    }

    .gg-craft-center::after{
        top:auto;
        bottom:0;
    }

    .gg-craft-center img{
        width:100%;
        height:auto;
        aspect-ratio:4 / 3;
        object-fit:cover;
        object-position:center;
        border:0;
    }

    .gg-craft-right{
        align-items:center;
        padding:34px 7% 42px;
        gap:24px;
    }

    .gg-feature{
        grid-template-columns:44px minmax(0, 1fr);
        gap:18px;
        width:min(100%, 360px);
    }

    .gg-feature-icon{
        width:44px;
        height:44px;
    }

    .gg-feature-text{
        font-size:clamp(16px, 5vw, 22px);
        line-height:1.35;
        letter-spacing:0.14em;
        text-align:left;
    }
}
</style>

    <?php
    return ob_get_clean();
});

/**
 * Gold Goblins Värdering(work)
 */
add_shortcode('gg_work', function() {
    ob_start();
    ?>

<section class="gg-workshop-section">

    <div class="gg-workshop-left">
        <?php
        echo wp_get_attachment_image(
            1475,
            'medium_large',
            false,
            [
                'class'    => 'gg-workshop-image',
                'loading'  => 'lazy',
                'decoding' => 'async',
                'alt'      => '',
                'sizes'    => '(max-width: 768px) 100vw, 32vw',
            ]
        );
        ?>
    </div>

    <div class="gg-workshop-center">

        <h2 class="gg-small-title">VÄRDERING</h2>

        <img
            class="gg-small-arrow"
            src="https://www.goldgoblins.se/wp-content/uploads/2026/06/e01we3r5y6tyjggretgh-1.webp"
            alt=""
            loading="lazy"
            decoding="async"
        >

        <div class="gg-workshop-heading">
            Analyserat.<br>
            Verifierat.<br>
            Värderat.
        </div>

        <p>
            Vi erbjuder värdering av smycken, guld, silver och andra ädelmetaller i Lidköping. Med noggrann analys av metallhalt, vikt, skick och utförande får du en tydlig bedömning av både metallvärde och uppskattat marknadsvärde.
        </p>

        <a href="/vardering/">VÄRDERING →</a>

    </div>

    <div class="gg-workshop-right">
        <?php
        echo wp_get_attachment_image(
            1470,
            'medium_large',
            false,
            [
                'class'    => 'gg-workshop-image',
                'loading'  => 'lazy',
                'decoding' => 'async',
                'alt'      => '',
                'sizes'    => '(max-width: 768px) 70vw, 26vw',
            ]
        );
        ?>
    </div>

</section>

<style>
.gg-workshop-section{
    position:relative;

    width:100%;
    display:grid;
    grid-template-columns:minmax(260px, 32%) minmax(0, 38%) minmax(220px, 30%);

   min-height:clamp(300px, 24vw, 430px);

    background-color:#f1dfc4;
    background-image:
        radial-gradient(circle at 20% 15%, rgba(255,255,255,0.10), transparent 30%),
        radial-gradient(circle at 80% 35%, rgba(120,90,55,0.03), transparent 35%),
        radial-gradient(circle at 45% 80%, rgba(255,255,255,0.06), transparent 30%),
        linear-gradient(135deg, rgba(255,255,255,0.03), rgba(120,90,55,0.02));
    background-size:cover;
    background-position:center;

    border-top:0;
    border-bottom:0;

    box-sizing:border-box;
    overflow:hidden;
    align-items:stretch;
}

.gg-workshop-section::before,
.gg-workshop-section::after{
    content:"";
    position:absolute;
    left:0;
    right:0;

    height:1px;

    background:linear-gradient(
        90deg,
        transparent 0%,
        rgba(159,133,96,0.28) 18%,
        rgba(159,133,96,0.70) 50%,
        rgba(159,133,96,0.28) 82%,
        transparent 100%
    );

    pointer-events:none;
    z-index:5;
}

.gg-workshop-section::before{
    top:0;
}

.gg-workshop-section::after{
    bottom:0;
}

.gg-workshop-left{
    position:relative;
    height:100%;
    display:flex;
    align-items:stretch;
    overflow:hidden;
}

.gg-workshop-left::after{
    content:"";
    position:absolute;
    top:0;
    right:0;
    bottom:0;
    width:1px;

    background:linear-gradient(
        180deg,
        transparent 0%,
        rgba(159,133,96,0.24) 18%,
        rgba(159,133,96,0.58) 50%,
        rgba(159,133,96,0.24) 82%,
        transparent 100%
    );

    pointer-events:none;
    z-index:2;
}

.gg-workshop-left img{
    width:100%;
    height:100%;
    object-fit:cover;
    object-position:center;
    display:block;
}

.gg-workshop-center{
    display:flex;
    flex-direction:column;
    justify-content:center;

    padding:clamp(28px, 3.2vw, 56px) clamp(34px, 4vw, 72px);
    box-sizing:border-box;
}

.gg-workshop-center .gg-small-title{
    color:#B9965F;
    font-family:'PT Serif', serif;
    font-size:clamp(18px, 1.45vw, 28px);
    letter-spacing:0.28em;
    line-height:1.2;
    font-weight:400;
    margin:0 0 clamp(8px, 0.8vw, 14px);
}

.gg-workshop-center .gg-small-arrow{
    width:clamp(74px, 5.5vw, 120px);
    height:auto;
    margin-bottom:clamp(18px, 1.8vw, 30px);
}

.gg-workshop-heading{
    font-family:'PT Serif', serif;
    color:#3a342c;
    font-size:clamp(30px, 2.25vw, 44px);
    line-height:1.24;
    letter-spacing:0.02em;
    margin:0 0 clamp(16px, 1.6vw, 26px);
    max-width:620px;
}

.gg-workshop-center p{
    font-family:'PT Serif', serif;
    color:#3a342c;
    font-size:clamp(14px, 1.05vw, 18px);
    line-height:1.65;
    max-width:38em;
    margin:0 0 clamp(18px, 1.8vw, 30px);
}

.gg-workshop-center a{
    position:relative;
    display:inline-block;
    width:fit-content;

    color:#3a342c;
    font-family:'PT Serif', serif;
    font-size:clamp(14px, 1.25vw, 19px);
    text-decoration:none;
    letter-spacing:0.24em;

    transition:color 0.25s ease;
    z-index:1;
}

.gg-workshop-center a::before{
    content:"";
    position:absolute;
    left:50%;
    top:50%;

    width:calc(100% + 12px);
    height:1.4em;

    transform:translate(-50%, -50%) scale(0.7);

    background:radial-gradient(
        ellipse at center,
        rgba(255,255,255,0.18) 0%,
        rgba(255,255,255,0.06) 50%,
        rgba(255,255,255,0) 100%
    );

    border-radius:999px;
    filter:blur(4px);

    opacity:0;

    transition:
        opacity 0.25s ease,
        transform 0.25s ease;

    pointer-events:none;
    z-index:-1;
}

.gg-workshop-center a:hover{
    color:#B9965F;
}

.gg-workshop-center a:hover::before{
    opacity:1;
    transform:translate(-50%, -50%) scale(1);
}

.gg-workshop-right{
    position:relative;

    min-height:100%;
    display:block;

    padding:0;
    box-sizing:border-box;
    overflow:hidden;
}

.gg-workshop-right::before{
    content:"";
    position:absolute;
    top:0;
    left:0;
    bottom:0;
    width:1px;

    background:linear-gradient(
        180deg,
        transparent 0%,
        rgba(159,133,96,0.16) 18%,
        rgba(159,133,96,0.42) 50%,
        rgba(159,133,96,0.16) 82%,
        transparent 100%
    );

    pointer-events:none;
    z-index:2;
}

.gg-workshop-right img{
    position:absolute;
    top:50%;
    right:-10%;

    width:auto;
    height:101%;
    max-width:none;

    object-fit:contain;
    display:block;

    opacity:0.42;
    filter:sepia(0.12);

    transform:translateY(-50%);
}

@media(max-width:900px){
    .gg-workshop-section{
        width:100vw;
        max-width:100vw;
        margin-left:calc(50% - 50vw);
        margin-right:calc(50% - 50vw);

        display:grid;
        grid-template-columns:1fr;

        min-height:auto;
    }

    .gg-workshop-center{
        order:1;
        padding:42px 7% 36px;
    }

    .gg-workshop-center .gg-small-title{
        font-size:clamp(24px, 7vw, 34px);
        letter-spacing:0.22em;
    }

    .gg-workshop-center .gg-small-arrow{
        width:100px;
        margin-bottom:24px;
    }

    .gg-workshop-heading{
        font-size:clamp(32px, 9vw, 44px);
        line-height:1.18;
        margin-bottom:22px;
    }

    .gg-workshop-center p{
        font-size:15px;
        line-height:1.65;
        margin-bottom:24px;
    }

    .gg-workshop-center a{
        font-size:14px;
        letter-spacing:0.15em;
    }

    .gg-workshop-left{
        order:2;
        height:auto;
    }

    .gg-workshop-left::after{
        top:0;
        left:0;
        right:0;
        bottom:auto;
        width:auto;
        height:1px;

        background:linear-gradient(
            90deg,
            transparent 0%,
            rgba(159,133,96,0.28) 18%,
            rgba(159,133,96,0.70) 50%,
            rgba(159,133,96,0.28) 82%,
            transparent 100%
        );
    }

    .gg-workshop-left img{
        width:100%;
        height:auto;
        aspect-ratio:4 / 3;
        object-fit:cover;
    }

    .gg-workshop-right{
        display:none;
    }
}
</style>

    <?php
    return ob_get_clean();
});

/**
 * Gold Chart
 */
add_shortcode('gg_gold_chart', function() {


    ob_start();
    ?>

		
		
<section class="gg-gold-chart-section">
    <div class="gg-gold-chart-heading">
        <h1 class="gg-small-title">Guldpris idag per gram</h1>

        <p>
            Här kan du följa det aktuella guldpriset på världsmarknaden.
            Priset används som en del av vår värdering av guld och andra ädelmetaller.
        </p>
    </div>

<div class="gg-gold-price-grid">
    <div class="gg-gold-price-card">
        <span>USD / G</span>
        <strong id="gg-usd-oz">Laddar...</strong>
        <em id="gg-usd-change" class="gg-price-change">Laddar...</em>
        <small id="gg-usd-g">Laddar...</small>
    </div>

    <div class="gg-gold-price-card">
        <span>SEK / G</span>
        <strong id="gg-sek-oz">Laddar...</strong>
        <em id="gg-sek-change" class="gg-price-change">Laddar...</em>
        <small id="gg-sek-g">Laddar...</small>
    </div>

    <div class="gg-gold-price-card">
        <span>EUR / G</span>
        <strong id="gg-eur-oz">Laddar...</strong>
        <em id="gg-eur-change" class="gg-price-change">Laddar...</em>
        <small id="gg-eur-g">Laddar...</small>
    </div>
</div>

   


    <div class="gg-gold-chart-box">
        <div class="gg-gold-chart-inner">
            <div id="gg-tradingview-gold"></div>
        </div>
    </div>

    <div class="gg-gold-chart-note">
    <div class="gg-gold-divider"></div>

    <p>
        Ett smyckes värde påverkas inte enbart av dagens guldpris, utan även av vikt,
        metallhalt, skick, design och eventuellt andrahandsvärde.
    </p>

    <a href="/silver/" class="gg-chart-button">
    SE AKTUELLA SILVERPRISER
</a>
</div>
</section>

		
				
				
				
<script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>

<script>
document.addEventListener('DOMContentLoaded', function() {
    if (!document.getElementById('gg-tradingview-gold')) return;

    new TradingView.widget({
        "width": "100%",
        "height": 410,
        "symbol": "TVC:GOLD",
        "interval": "D",
        "timezone": "Europe/Stockholm",
        "theme": "light",
        "style": "3",
        "locale": "sv_SE",

        "toolbar_bg": "#f1dfc4",
        "backgroundColor": "#f1dfc4",
        "gridColor": "rgba(185,150,95,0.10)",

        "enable_publishing": false,
        "hide_top_toolbar": false,
        "hide_side_toolbar": true,
        "hide_legend": false,
        "save_image": false,
        "allow_symbol_change": false,

        "studies": [],
        "disabled_features": [
            "volume_force_overlay",
            "create_volume_indicator_by_default",
            "header_symbol_search",
            "header_compare",
            "header_screenshot",
            "header_saveload",
            "header_fullscreen_button",
            "left_toolbar",
            "control_bar",
            "timeframes_toolbar",
            "use_localstorage_for_settings"
        ],

        "overrides": {
            "paneProperties.background": "#f1dfc4",
            "paneProperties.backgroundType": "solid",
            "paneProperties.vertGridProperties.color": "rgba(185,150,95,0.10)",
            "paneProperties.horzGridProperties.color": "rgba(185,150,95,0.10)",

            "scalesProperties.textColor": "#2f2b25",
            "scalesProperties.lineColor": "rgba(170,138,88,0.35)",

            "mainSeriesProperties.areaStyle.color1": "rgba(185,150,95,0.30)",
            "mainSeriesProperties.areaStyle.color2": "rgba(185,150,95,0.03)",
            "mainSeriesProperties.areaStyle.linecolor": "#9f782e",
            "mainSeriesProperties.areaStyle.linewidth": 2,

            "mainSeriesProperties.lineStyle.color": "#9f782e",
            "mainSeriesProperties.lineStyle.linewidth": 2,

            "mainSeriesProperties.priceLineColor": "#9f782e",
            "mainSeriesProperties.priceLineWidth": 1
        },

        "studies_overrides": {
            "volume.volume.visible": false
        },

        "container_id": "gg-tradingview-gold"
    });
});
</script>

	<script>
document.addEventListener('DOMContentLoaded', function() {
    const gramPerOz = 31.1034768;

    function format(value, currency) {
        return new Intl.NumberFormat('sv-SE', {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2
        }).format(value) + ' ' + currency;
    }

    function formatChange(value) {
        const sign = value > 0 ? '+' : '';
        return sign + new Intl.NumberFormat('sv-SE', {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2
        }).format(value) + '% idag';
    }

    function setChange(id, value) {
        const el = document.getElementById(id);
        if (!el) return;

        el.textContent = (value >= 0 ? '▲ ' : '▼ ') + formatChange(value);
        el.classList.remove('up', 'down');
        el.classList.add(value >= 0 ? 'up' : 'down');
    }

    async function getTVQuote(symbol) {
        const url = 'https://scanner.tradingview.com/symbol?symbol=' + encodeURIComponent(symbol) + '&fields=close,change';
        const response = await fetch(url);
        const data = await response.json();

        if (!data || typeof data.close !== 'number') {
            throw new Error('Kunde inte hämta ' + symbol);
        }

        return {
            close: data.close,
            change: typeof data.change === 'number' ? data.change : 0
        };
    }

    async function updateGoldPrices() {
        try {
            const gold = await getTVQuote('TVC:GOLD');
            const usdSek = await getTVQuote('FX_IDC:USDSEK');
            const eurUsd = await getTVQuote('FX_IDC:EURUSD');

            const usdOz = gold.close;
            const usdG = usdOz / gramPerOz;

            const sekOz = usdOz * usdSek.close;
            const sekG = sekOz / gramPerOz;

            const eurOz = usdOz / eurUsd.close;
            const eurG = eurOz / gramPerOz;

            document.getElementById('gg-usd-oz').textContent = format(usdG, 'USD');
            document.getElementById('gg-usd-g').textContent = format(usdOz, 'USD/oz');
            setChange('gg-usd-change', gold.change);

            document.getElementById('gg-sek-oz').textContent = format(sekG, 'SEK');
			document.getElementById('gg-sek-g').textContent = format(sekOz, 'SEK/oz');
            setChange('gg-sek-change', gold.change + usdSek.change);

            document.getElementById('gg-eur-oz').textContent = format(eurG, 'EUR');
            document.getElementById('gg-eur-g').textContent = format(eurOz, 'EUR/oz');
            setChange('gg-eur-change', gold.change - eurUsd.change);

        } catch (error) {
            document.getElementById('gg-usd-oz').textContent = 'Visas i grafen';
            document.getElementById('gg-usd-g').textContent = '1 oz = 31,1035 g';

            document.getElementById('gg-sek-oz').textContent = 'Valutakurs saknas';
            document.getElementById('gg-sek-g').textContent = 'Försök igen senare';

            document.getElementById('gg-eur-oz').textContent = 'Valutakurs saknas';
            document.getElementById('gg-eur-g').textContent = 'Försök igen senare';
        }
    }

    updateGoldPrices();
});
</script>
	
<style>
.gg-gold-chart-section {
    padding: clamp(55px, 6vw, 95px) 6%;
    text-align: center;
    background-color: #f1dfc4;
    background-image:
        radial-gradient(circle at 20% 15%, rgba(255,255,255,0.10), transparent 30%),
        radial-gradient(circle at 80% 35%, rgba(120,90,55,0.03), transparent 35%),
        radial-gradient(circle at 45% 80%, rgba(255,255,255,0.06), transparent 30%),
        linear-gradient(135deg, rgba(255,255,255,0.03), rgba(120,90,55,0.02));
    background-size: cover;
    background-position: center;
}

.gg-gold-chart-heading {
    max-width: 860px;
    margin: 0 auto clamp(30px, 3vw, 42px);
}

.gg-gold-chart-heading .gg-small-title {
    color: #B9965F;
}

.gg-gold-chart-heading p {
    max-width: 780px;
    margin: 18px auto 0;
    font-family: 'PT Serif', Georgia, serif;
    font-size: clamp(14px, 1.15vw, 17px);
    line-height: 1.8;
    color: #2f2b25;
}

.gg-gold-price-grid {
    width: min(90vw, 1220px);
    margin: 0 auto clamp(22px, 2.4vw, 34px);
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: clamp(10px, 1.2vw, 18px);
}

.gg-gold-price-card {
    padding: clamp(14px, 1.4vw, 22px);
    border: 1px solid rgba(170, 138, 88, 0.65);
    background:
        radial-gradient(circle at 20% 15%, rgba(255,255,255,0.13), transparent 32%),
        rgba(241, 223, 196, 0.74);
    box-shadow: 0 10px 28px rgba(80, 55, 30, 0.10);
}

.gg-gold-price-card span {
    display: block;
    margin-bottom: 8px;
    color: #B9965F;
    font-family: Georgia, "Times New Roman", serif;
    font-size: clamp(10px, 0.75vw, 12px);
    letter-spacing: 0.22em;
}

.gg-gold-price-card strong {
    display: block;
    color: #2f2b25;
    
    font-size: clamp(18px, 1.7vw, 28px);
    font-weight: 400;
    line-height: 1.15;
}

.gg-price-change {
    display: block;
    margin-top: 7px;
    font-style: normal;
    font-size: 13px;
    font-weight: 500;
    letter-spacing: 0.03em;
}

.gg-price-change.up {
    color: #4f7d52;
}

.gg-price-change.down {
    color: #9a5349;
}

.gg-gold-price-card small {
    display: block;
    margin-top: 6px;
    color: rgba(47, 43, 37, 0.68);
    font-size: clamp(12px, 0.9vw, 15px);
}

.gg-gold-chart-box {
    width: min(90vw, 1220px);
    margin: 0 auto;
    padding: clamp(16px, 1.8vw, 26px);
    border: 2px solid #aa8a58;
    background-color: #f1dfc4;
    background-image:
        radial-gradient(circle at 20% 15%, rgba(255,255,255,0.10), transparent 30%),
        radial-gradient(circle at 80% 35%, rgba(120,90,55,0.03), transparent 35%),
        radial-gradient(circle at 45% 80%, rgba(255,255,255,0.06), transparent 30%),
        linear-gradient(135deg, rgba(255,255,255,0.03), rgba(120,90,55,0.02));
    background-size: cover;
    background-position: center;
    box-shadow: 0 18px 45px rgba(80, 55, 30, 0.16);
}

.gg-gold-chart-inner {
    overflow: hidden;
    border: 1px solid rgba(170, 138, 88, 0.5);
    background: #f1dfc4;
}

#gg-tradingview-gold {
    width: 100%;
    height: 410px;
}

.gg-gold-chart-note {
    max-width: 800px;
    margin: 30px auto 0;
}

.gg-gold-divider {
    width: 150px;
    height: 1px;
    margin: 0 auto 18px;
    background: linear-gradient(
        90deg,
        transparent,
        rgba(170, 138, 88, 0.8),
        transparent
    );
}

.gg-gold-chart-note p {
    margin: 0;
    font-family: 'PT Serif', Georgia, serif;
    font-size: 14px;
    line-height: 1.75;
    color: #2f2b25;
}

.gg-chart-button{
    display:inline-flex;
    align-items:center;
    justify-content:center;

    margin-top:24px;
    padding:12px 24px;

    border:1px solid #B9965F;
    color:#3a342c;
    background:transparent;

    text-decoration:none;
    font-family:'PT Serif', serif;
    font-size:clamp(13px, 0.95vw, 16px);
    letter-spacing:0.18em;

    transition:
        color .25s ease,
        border-color .25s ease,
        background-color .25s ease,
        transform .25s ease,
        box-shadow .25s ease;
}

.gg-chart-button:hover{
    color:#B9965F;
    border-color:#c4a26d;
    background:rgba(255,255,255,0.08);
    box-shadow:0 4px 12px rgba(0,0,0,0.08);
    transform:translateY(-1px);
}
			  
@media (max-width: 768px) {
    .gg-gold-chart-section {
        padding: 48px 4%;
    }

    .gg-gold-price-grid {
        width: 100%;
        grid-template-columns: 1fr;
    }

    .gg-gold-chart-box {
        width: 100%;
        padding: 10px;
    }

    #gg-tradingview-gold {
        height: 340px;
    }
}
			  
			  
</style>

    <?php
    return ob_get_clean();
});

/**
 * Silver chart
 */
add_shortcode('gg_silver_chart', function() {

    ob_start();
    ?>

<section class="gg-gold-chart-section">
    <div class="gg-gold-chart-heading">
        <h1 class="gg-small-title">Silverpris idag per gram</h1>

        <p>
            Här kan du följa det aktuella silverpriset på världsmarknaden.
            Priset används som en del av vår värdering av silver och andra ädelmetaller.
        </p>
    </div>

    <div class="gg-gold-price-grid">
        <div class="gg-gold-price-card">
            <span>USD / G</span>
            <strong id="gg-silver-usd-oz">Laddar...</strong>
            <em id="gg-silver-usd-change" class="gg-price-change">Laddar...</em>
            <small id="gg-silver-usd-g">Laddar...</small>
        </div>

        <div class="gg-gold-price-card">
            <span>SEK / G</span>
            <strong id="gg-silver-sek-oz">Laddar...</strong>
            <em id="gg-silver-sek-change" class="gg-price-change">Laddar...</em>
            <small id="gg-silver-sek-g">Laddar...</small>
        </div>

        <div class="gg-gold-price-card">
            <span>EUR / G</span>
            <strong id="gg-silver-eur-oz">Laddar...</strong>
            <em id="gg-silver-eur-change" class="gg-price-change">Laddar...</em>
            <small id="gg-silver-eur-g">Laddar...</small>
        </div>
    </div>

    <div class="gg-gold-chart-box">
        <div class="gg-gold-chart-inner">
            <div id="gg-tradingview-silver"></div>
        </div>
    </div>

    <div class="gg-gold-chart-note">
        <div class="gg-gold-divider"></div>
        <p>
            Ett smyckes värde påverkas inte enbart av dagens silverpris, utan även av vikt,
            metallhalt, skick, design och eventuellt andrahandsvärde.
        </p>
				
				<a href="/guld/" class="gg-chart-button">
    			SE AKTUELLA GULDPRISER
</a>
				
    </div>
</section>

<script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>

<script>
document.addEventListener('DOMContentLoaded', function() {
    if (!document.getElementById('gg-tradingview-silver')) return;

    new TradingView.widget({
        "width": "100%",
        "height": 410,
        "symbol": "TVC:SILVER",
        "interval": "D",
        "timezone": "Europe/Stockholm",
        "theme": "light",
        "style": "3",
        "locale": "sv_SE",

        "toolbar_bg": "#f1dfc4",
        "backgroundColor": "#f1dfc4",
        "gridColor": "rgba(185,150,95,0.10)",

        "enable_publishing": false,
        "hide_top_toolbar": false,
        "hide_side_toolbar": true,
        "hide_legend": false,
        "save_image": false,
        "allow_symbol_change": false,

        "studies": [],
        "disabled_features": [
            "volume_force_overlay",
            "create_volume_indicator_by_default",
            "header_symbol_search",
            "header_compare",
            "header_screenshot",
            "header_saveload",
            "header_fullscreen_button",
            "left_toolbar",
            "control_bar",
            "timeframes_toolbar",
            "use_localstorage_for_settings"
        ],

        "overrides": {
            "paneProperties.background": "#f1dfc4",
            "paneProperties.backgroundType": "solid",
            "paneProperties.vertGridProperties.color": "rgba(185,150,95,0.10)",
            "paneProperties.horzGridProperties.color": "rgba(185,150,95,0.10)",

            "scalesProperties.textColor": "#2f2b25",
            "scalesProperties.lineColor": "rgba(170,138,88,0.35)",

            "mainSeriesProperties.areaStyle.color1": "rgba(185,150,95,0.30)",
            "mainSeriesProperties.areaStyle.color2": "rgba(185,150,95,0.03)",
            "mainSeriesProperties.areaStyle.linecolor": "#9f782e",
            "mainSeriesProperties.areaStyle.linewidth": 2,

            "mainSeriesProperties.lineStyle.color": "#9f782e",
            "mainSeriesProperties.lineStyle.linewidth": 2,

            "mainSeriesProperties.priceLineColor": "#9f782e",
            "mainSeriesProperties.priceLineWidth": 1
        },

        "studies_overrides": {
            "volume.volume.visible": false
        },

        "container_id": "gg-tradingview-silver"
    });
});
</script>

<script>
document.addEventListener('DOMContentLoaded', function() {
    const gramPerOz = 31.1034768;

    function format(value, currency) {
        return new Intl.NumberFormat('sv-SE', {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2
        }).format(value) + ' ' + currency;
    }

    function formatChange(value) {
        const sign = value > 0 ? '+' : '';
        return sign + new Intl.NumberFormat('sv-SE', {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2
        }).format(value) + '% idag';
    }

    function setChange(id, value) {
        const el = document.getElementById(id);
        if (!el) return;

        el.textContent = (value >= 0 ? '▲ ' : '▼ ') + formatChange(value);
        el.classList.remove('up', 'down');
        el.classList.add(value >= 0 ? 'up' : 'down');
    }

    async function getTVQuote(symbol) {
        const url = 'https://scanner.tradingview.com/symbol?symbol=' + encodeURIComponent(symbol) + '&fields=close,change';
        const response = await fetch(url);
        const data = await response.json();

        if (!data || typeof data.close !== 'number') {
            throw new Error('Kunde inte hämta ' + symbol);
        }

        return {
            close: data.close,
            change: typeof data.change === 'number' ? data.change : 0
        };
    }

    async function updateSilverPrices() {
        try {
            const silver = await getTVQuote('TVC:SILVER');
            const usdSek = await getTVQuote('FX_IDC:USDSEK');
            const eurUsd = await getTVQuote('FX_IDC:EURUSD');

            const usdOz = silver.close;
            const usdG = usdOz / gramPerOz;

            const sekOz = usdOz * usdSek.close;
            const sekG = sekOz / gramPerOz;

            const eurOz = usdOz / eurUsd.close;
            const eurG = eurOz / gramPerOz;

            document.getElementById('gg-silver-usd-oz').textContent = format(usdG, 'USD');
            document.getElementById('gg-silver-usd-g').textContent = format(usdOz, 'USD/oz');
            setChange('gg-silver-usd-change', silver.change);

            document.getElementById('gg-silver-sek-oz').textContent = format(sekG, 'SEK');
			document.getElementById('gg-silver-sek-g').textContent = format(sekOz, 'SEK/oz');
            setChange('gg-silver-sek-change', silver.change + usdSek.change);

            document.getElementById('gg-silver-eur-oz').textContent = format(eurG, 'EUR');
            document.getElementById('gg-silver-eur-g').textContent = format(eurOz, 'EUR/oz');
            setChange('gg-silver-eur-change', silver.change - eurUsd.change);

        } catch (error) {
            document.getElementById('gg-silver-usd-oz').textContent = 'Visas i grafen';
            document.getElementById('gg-silver-usd-g').textContent = '1 oz = 31,1035 g';

            document.getElementById('gg-silver-sek-oz').textContent = 'Valutakurs saknas';
            document.getElementById('gg-silver-sek-g').textContent = 'Försök igen senare';

            document.getElementById('gg-silver-eur-oz').textContent = 'Valutakurs saknas';
            document.getElementById('gg-silver-eur-g').textContent = 'Försök igen senare';
        }
    }

    updateSilverPrices();
});
</script>

<style>
.gg-gold-chart-section {
    padding: clamp(55px, 6vw, 95px) 6%;
    text-align: center;
    background-color: #f1dfc4;
    background-image:
        radial-gradient(circle at 20% 15%, rgba(255,255,255,0.10), transparent 30%),
        radial-gradient(circle at 80% 35%, rgba(120,90,55,0.03), transparent 35%),
        radial-gradient(circle at 45% 80%, rgba(255,255,255,0.06), transparent 30%),
        linear-gradient(135deg, rgba(255,255,255,0.03), rgba(120,90,55,0.02));
    background-size: cover;
    background-position: center;
}

.gg-gold-chart-heading {
    max-width: 860px;
    margin: 0 auto clamp(30px, 3vw, 42px);
}

.gg-gold-chart-heading .gg-small-title {
    color: #B9965F;
}

.gg-gold-chart-heading p {
    max-width: 780px;
    margin: 18px auto 0;
    font-family: 'PT Serif', Georgia, serif;
    font-size: clamp(14px, 1.15vw, 17px);
    line-height: 1.8;
    color: #2f2b25;
}

.gg-gold-price-grid {
    width: min(90vw, 1220px);
    margin: 0 auto clamp(22px, 2.4vw, 34px);
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: clamp(10px, 1.2vw, 18px);
}

.gg-gold-price-card {
    padding: clamp(14px, 1.4vw, 22px);
    border: 1px solid rgba(170, 138, 88, 0.65);
    background:
        radial-gradient(circle at 20% 15%, rgba(255,255,255,0.13), transparent 32%),
        rgba(241, 223, 196, 0.74);
    box-shadow: 0 10px 28px rgba(80, 55, 30, 0.10);
}

.gg-gold-price-card span {
    display: block;
    margin-bottom: 8px;
    color: #B9965F;
    font-family: Georgia, "Times New Roman", serif;
    font-size: clamp(10px, 0.75vw, 12px);
    letter-spacing: 0.22em;
}

.gg-gold-price-card strong {
    display: block;
    color: #2f2b25;
    
    font-size: clamp(18px, 1.7vw, 28px);
    font-weight: 400;
    line-height: 1.15;
}

.gg-price-change {
    display: block;
    margin-top: 7px;
    font-style: normal;
    font-size: 13px;
    font-weight: 500;
    letter-spacing: 0.03em;
}

.gg-price-change.up {
    color: #4f7d52;
}

.gg-price-change.down {
    color: #9a5349;
}

.gg-gold-price-card small {
    display: block;
    margin-top: 6px;
    color: rgba(47, 43, 37, 0.68);
    font-size: clamp(12px, 0.9vw, 15px);
}

.gg-gold-chart-box {
    width: min(90vw, 1220px);
    margin: 0 auto;
    padding: clamp(16px, 1.8vw, 26px);
    border: 2px solid #aa8a58;
    background-color: #f1dfc4;
    background-image:
        radial-gradient(circle at 20% 15%, rgba(255,255,255,0.10), transparent 30%),
        radial-gradient(circle at 80% 35%, rgba(120,90,55,0.03), transparent 35%),
        radial-gradient(circle at 45% 80%, rgba(255,255,255,0.06), transparent 30%),
        linear-gradient(135deg, rgba(255,255,255,0.03), rgba(120,90,55,0.02));
    background-size: cover;
    background-position: center;
    box-shadow: 0 18px 45px rgba(80, 55, 30, 0.16);
}

.gg-gold-chart-inner {
    overflow: hidden;
    border: 1px solid rgba(170, 138, 88, 0.5);
    background: #f1dfc4;
}

#gg-tradingview-gold {
    width: 100%;
    height: 410px;
}

.gg-gold-chart-note {
    max-width: 800px;
    margin: 30px auto 0;
}

.gg-gold-divider {
    width: 150px;
    height: 1px;
    margin: 0 auto 18px;
    background: linear-gradient(
        90deg,
        transparent,
        rgba(170, 138, 88, 0.8),
        transparent
    );
}

.gg-gold-chart-note p {
    margin: 0;
    font-family: 'PT Serif', Georgia, serif;
    font-size: 14px;
    line-height: 1.75;
    color: #2f2b25;
}

			  .gg-chart-button{
    display:inline-flex;
    align-items:center;
    justify-content:center;

    margin-top:24px;
    padding:12px 24px;

    border:1px solid #B9965F;
    color:#3a342c;
    background:transparent;

    text-decoration:none;
    font-family:'PT Serif', serif;
    font-size:clamp(13px, 0.95vw, 16px);
    letter-spacing:0.18em;

    transition:
        color .25s ease,
        border-color .25s ease,
        background-color .25s ease,
        transform .25s ease,
        box-shadow .25s ease;
}

.gg-chart-button:hover{
    color:#B9965F;
    border-color:#c4a26d;
    background:rgba(255,255,255,0.08);
    box-shadow:0 4px 12px rgba(0,0,0,0.08);
    transform:translateY(-1px);
}
			  
@media (max-width: 768px) {
    .gg-gold-chart-section {
        padding: 48px 4%;
    }

    .gg-gold-price-grid {
        width: 100%;
        grid-template-columns: 1fr;
    }

    .gg-gold-chart-box {
        width: 100%;
        padding: 10px;
    }

    #gg-tradingview-gold {
        height: 340px;
    }
}
</style>

    <?php
    return ob_get_clean();
});

/**
 * Ta bort jQuery Migrate
 */
add_action('wp_default_scripts', function ($scripts) {
    if (!is_admin() && isset($scripts->registered['jquery'])) {
        $scripts->registered['jquery']->deps = array_diff(
            $scripts->registered['jquery']->deps,
            ['jquery-migrate']
        );
    }
});

/**
 * Gold Goblins Schema.org
 */
add_action('wp_head', function() {

    if (is_admin()) {
        return;
    }

    $site_url = home_url('/');

    global $wp;

    $current_url = is_front_page()
        ? $site_url
        : trailingslashit(home_url($wp->request));

    $logo_url = 'https://www.goldgoblins.se/wp-content/uploads/2026/06/Gold_Goblins_Logga.webp';

    $business_id = $site_url . '#organization';
    $website_id  = $site_url . '#website';
    $webpage_id  = $current_url . '#webpage';

    $graph = [];

    /*
     * Grundschema för Gold Goblins.
     * Ligger på alla publika sidor.
     */
    $graph[] = [
        '@type' => ['JewelryStore', 'LocalBusiness'],
        '@id'   => $business_id,
        'name'  => 'Gold Goblins',
        'url'   => $site_url,

        'logo' => [
            '@type' => 'ImageObject',
            'url'   => $logo_url,
        ],

        'image' => [
            '@type' => 'ImageObject',
            'url'   => $logo_url,
        ],

        'email' => 'kontakt@goldgoblins.se',

        'address' => [
            '@type'           => 'PostalAddress',
            'streetAddress'   => 'Stockvägen 4',
            'postalCode'      => '531 53',
            'addressLocality' => 'Lidköping',
            'addressCountry'  => 'SE',
        ],

        'areaServed' => [
            '@type' => 'Country',
            'name'  => 'Sverige',
        ],

        'priceRange' => '$$',

        'description' => 'Gold Goblins är en svensk smyckesverkstad i Lidköping som erbjuder handgjorda smycken, silversmycken, guldsmycken, specialbeställningar, smyckesvärdering och återbruk av ädelmetaller. Besök sker enligt överenskommelse.',

        'additionalProperty' => [
            [
                '@type' => 'PropertyValue',
                'name'  => 'Besök',
                'value' => 'Besök enligt överenskommelse',
            ],
            [
                '@type' => 'PropertyValue',
                'name'  => 'Organisationsnummer',
                'value' => '969799-8897',
            ],
        ],

        'knowsAbout' => [
            'Handgjorda smycken',
            'Silversmycken',
            'Guldsmycken',
            'Smyckesvärdering',
            'Specialbeställningar',
            'Återbruk av ädelmetaller',
            'Guldpris',
            'Silverpris',
            'Smyckesverkstad',
        ],
    ];

    /*
     * WebSite-schema.
     */
    $graph[] = [
        '@type' => 'WebSite',
        '@id'   => $website_id,
        'url'   => $site_url,
        'name'  => 'Gold Goblins',
        'publisher' => [
            '@id' => $business_id,
        ],
        'inLanguage' => 'sv-SE',
    ];

    /*
     * WebPage-schema för aktuell sida.
     */
    $graph[] = [
        '@type' => 'WebPage',
        '@id'   => $webpage_id,
        'url'   => $current_url,
        'name'  => wp_get_document_title(),
        'isPartOf' => [
            '@id' => $website_id,
        ],
        'about' => [
            '@id' => $business_id,
        ],
        'inLanguage' => 'sv-SE',
    ];

    /*
     * Service-schema för värderingssidan.
     */
    if (is_page('vardering')) {
        $graph[] = [
            '@type' => 'Service',
            '@id'   => home_url('/vardering/') . '#service',
            'name'  => 'Värdering av smycken, guld och silver',
            'serviceType' => 'Smyckesvärdering och analys av ädelmetaller',
            'url'   => home_url('/vardering/'),

            'provider' => [
                '@id' => $business_id,
            ],

            'areaServed' => [
                '@type' => 'Place',
                'name'  => 'Lidköping och Sverige',
            ],

            'description' => 'Gold Goblins erbjuder professionell värdering av smycken, guld, silver, platina och andra ädelmetaller i Lidköping med analys av metallhalt, skick, utförande, märkningar och uppskattat marknadsvärde.',

            'offers' => [
                [
                    '@type' => 'Offer',
                    'name' => 'Värdering av 1 smycke',
                    'price' => '500',
                    'priceCurrency' => 'SEK',
                    'availability' => 'https://schema.org/InStock',
                    'url' => home_url('/vardering/'),
                ],
                [
                    '@type' => 'Offer',
                    'name' => 'Värdering av 2–5 smycken',
                    'price' => '400',
                    'priceCurrency' => 'SEK',
                    'availability' => 'https://schema.org/InStock',
                    'url' => home_url('/vardering/'),
                ],
            ],
        ];
    }

    /*
     * FAQPage-schema för kontaktsidan.
     * Frågorna ska matcha synliga frågor på kontaktsidan.
     */
    if (is_page('kontakta-oss')) {
        $graph[] = [
            '@type' => 'FAQPage',
            '@id'   => home_url('/kontakta-oss/') . '#faq',
            'mainEntity' => [
                [
                    '@type' => 'Question',
                    'name' => 'Är era smycken handgjorda?',
                    'acceptedAnswer' => [
                        '@type' => 'Answer',
                        'text' => 'Ja, många av våra smycken tillverkas för hand i vår verkstad med fokus på kvalitet, hantverk och hållbarhet.',
                    ],
                ],
                [
                    '@type' => 'Question',
                    'name' => 'Vilka material använder ni?',
                    'acceptedAnswer' => [
                        '@type' => 'Answer',
                        'text' => 'Gold Goblins arbetar bland annat med silver, guld och andra ädelmetaller. Vi kan även återbruka kundens egna metaller vid särskilda uppdrag.',
                    ],
                ],
                [
                    '@type' => 'Question',
                    'name' => 'Kan jag beställa ett specialdesignat smycke?',
                    'acceptedAnswer' => [
                        '@type' => 'Answer',
                        'text' => 'Ja, vi erbjuder specialbeställningar och skräddarsydda lösningar. Kontakta oss gärna för att diskutera dina idéer, material och pris.',
                    ],
                ],
                [
                    '@type' => 'Question',
                    'name' => 'Hur sköter jag mitt smycke?',
                    'acceptedAnswer' => [
                        '@type' => 'Answer',
                        'text' => 'För bästa hållbarhet rekommenderar vi att du förvarar smycket torrt, undviker starka kemikalier och rengör det regelbundet med lämpliga produkter för ädelmetaller.',
                    ],
                ],
                [
                    '@type' => 'Question',
                    'name' => 'Hur hittar jag rätt ringstorlek?',
                    'acceptedAnswer' => [
                        '@type' => 'Answer',
                        'text' => 'För att hitta rätt storlek rekommenderar vi att du använder vår storleksguide för ringar, där du hittar instruktioner för mätning och storlekstabeller.',
                    ],
                ],
                [
                    '@type' => 'Question',
                    'name' => 'Vilken längd ska jag välja på mitt halsband?',
                    'acceptedAnswer' => [
                        '@type' => 'Answer',
                        'text' => 'Valet av halsbandslängd är individuellt och beror på önskad passform. Se vår storleksguide för halsband för att jämföra olika längder och hitta den som passar dig bäst.',
                    ],
                ],
                [
                    '@type' => 'Question',
                    'name' => 'Hur lång är leveranstiden?',
                    'acceptedAnswer' => [
                        '@type' => 'Answer',
                        'text' => 'Leveranstiden varierar beroende på produkt och aktuell arbetsbelastning. Många smycken tillverkas för hand. Normal leveranstid är vanligtvis några arbetsdagar upp till två veckor, med maximal leveranstid 14 dagar från beställningstillfället.',
                    ],
                ],
                [
                    '@type' => 'Question',
                    'name' => 'Vad kostar frakten?',
                    'acceptedAnswer' => [
                        '@type' => 'Answer',
                        'text' => 'Vi erbjuder gratis frakt på alla beställningar över 1 000 kr. För beställningar under detta belopp tillkommer fraktkostnad enligt aktuell prislista i kassan.',
                    ],
                ],
                [
                    '@type' => 'Question',
                    'name' => 'Levererar ni internationellt?',
                    'acceptedAnswer' => [
                        '@type' => 'Answer',
                        'text' => 'Nej, för närvarande levererar vi endast inom Sverige.',
                    ],
                ],
                [
                    '@type' => 'Question',
                    'name' => 'Kan jag returnera en vara?',
                    'acceptedAnswer' => [
                        '@type' => 'Answer',
                        'text' => 'Ja, som privatkund har du enligt svensk lag 14 dagars ångerrätt från det att du mottagit din beställning.',
                    ],
                ],
                [
                    '@type' => 'Question',
                    'name' => 'Kan jag returnera specialtillverkade produkter?',
                    'acceptedAnswer' => [
                        '@type' => 'Answer',
                        'text' => 'Nej, ångerrätten gäller normalt inte för specialbeställda, personligt anpassade eller graverade produkter som tillverkats specifikt efter kundens önskemål.',
                    ],
                ],
                [
                    '@type' => 'Question',
                    'name' => 'Erbjuder ni värdering av smycken?',
                    'acceptedAnswer' => [
                        '@type' => 'Answer',
                        'text' => 'Ja, Gold Goblins erbjuder värdering av smycken, guld, silver, platina och andra ädelmetaller. Värderingen kan användas vid exempelvis försäkring, arvskifte, försäljning eller dokumentation.',
                    ],
                ],
            ],
        ];
    }

    $schema = [
        '@context' => 'https://schema.org',
        '@graph'   => $graph,
    ];

    echo "\n" . '<script type="application/ld+json">' . "\n";
    echo wp_json_encode($schema, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_PRETTY_PRINT);
    echo "\n" . '</script>' . "\n";

}, 20);

/**
 * Gold Goblins Verksamhet
 */
add_shortcode('gg_verksamhet', function() {
    ob_start();
    ?>
		<section class="gg-about-page"> 
<div class="gg-about-heading"> 
<img class="gg-heading-image" src="https://www.goldgoblins.se/wp-content/uploads/2026/06/9b12-49af-8218-3f9fa75d735a.webp" alt=""> 

<h1 class="gg-small-title">Smyckesverkstad i Lidköping</h1> 

<img class="gg-heading-image" src="https://www.goldgoblins.se/wp-content/uploads/2026/06/e018b.webp" alt=""> 

</div> <div class="gg-about-content"> <div class="gg-about-text"> 


<p> <br>Gold Goblins är en smyckesverkstad i Lidköping där handgjorda smycken, hållbara material och personlig formgivning står i centrum. Vi arbetar med silver, guld och andra ädelmetaller för att skapa smycken med tydlig karaktär, hög kvalitet och lång livslängd. </p>


 <p> I verkstaden tillverkar vi ringar, halsband, armband, hängsmycken och andra personliga smycken för hand. Varje arbete börjar med en idé, en form eller ett behov, och utvecklas steg för steg till ett färdigt smycke med genomtänkta proportioner, materialval och detaljer. </p> 

<p> Vi erbjuder även specialbeställningar för dig som vill skapa ett unikt smycke från grunden eller omarbeta ett befintligt föremål. Det kan handla om ett nytt smycke för ett särskilt tillfälle, en personlig modell, en gåva eller ett smycke där gammalt material får nytt liv. </p> 

<p>En viktig del av vår verksamhet är återbruk av ädelmetaller. Genom att arbeta med återvunnet guld och silver kan vi ta tillvara på material som redan finns i omlopp och skapa nya smycken med både historia och framtid. Det gör varje föremål mer personligt och minskar behovet av nyutvunna resurser.
</p> 

<p> Traditionellt silversmide och guldsmide kombineras med moderna verktyg, digital design och 3D-teknik när det behövs. På så sätt kan vi arbeta med hög precision utan att förlora känslan av äkta hantverk. Tekniken hjälper oss att utveckla formen, men det är fortfarande handens arbete som ger smycket dess slutliga uttryck.</p> 

<p>
    Utöver tillverkning och specialbeställningar erbjuder vi även värdering av smycken och ädelmetaller. Vill du veta mer om den processen finns fördjupad information på vår <a href="/vardering/">värderingssida</a>.
</p>

<p>
    Målet med Gold Goblins är att förena svenskt hantverk, noggrant utvalda material och personlig service. Oavsett om du vill köpa ett handgjort smycke, beställa något unikt, återbruka ädelmetaller eller få rådgivning kring ett föremål hjälper vi dig med en lösning som känns genomarbetad från början till slut.
</p>

</div> <div class="gg-about-image"> <img src="https://www.goldgoblins.se/wp-content/uploads/2026/06/Gold_Goblins_Verkstad_lokal_Lidkoping.webp" alt=""> </div> </div> </section> <style>
.gg-about-page{
    width:100%;
    background-color: #f1dfc4;

background-image:
    radial-gradient(circle at 20% 15%, rgba(255,255,255,0.10), transparent 30%),
    radial-gradient(circle at 80% 35%, rgba(120,90,55,0.03), transparent 35%),
    radial-gradient(circle at 45% 80%, rgba(255,255,255,0.06), transparent 30%),
    linear-gradient(135deg, rgba(255,255,255,0.03), rgba(120,90,55,0.02));
    background-size: cover;
    background-position: center;
    padding:clamp(50px,6vw,110px) 2%;
    box-sizing:border-box;
    border-top:0px solid #9F8560;
    border-bottom:0px solid #9F8560;
}

.gg-about-heading{
    max-width:950px;
    margin:0 auto clamp(40px,4vw,70px);
    display:grid;
    grid-template-columns:1fr auto 1fr;
    align-items:center;
    gap:clamp(20px,3vw,60px);
}

.gg-heading-image{
    width:100%;
    height:auto;
    display:block;
}

.gg-about-heading .gg-small-title{
    color:#B9965F;
    font-family:'PT Serif', serif;
    font-size:clamp(18px,2.2vw,32px);
    letter-spacing:0.35em;
    white-space:nowrap;
}

.gg-about-heading h1.gg-small-title{
    margin:0;
    font-weight:400;
    line-height:normal;
}

.gg-about-content{
    display:grid;

    /* K1     K2     K3      K4      K5 */
    grid-template-columns: 28% 15% 9% 43% 5%;

    gap:clamp(20px,2vw,40px);
    align-items:start;
    width:100%;
}

.gg-about-text{
    grid-column:1 / 3;
    text-align:left;
}

.gg-about-text p{
    font-family:'PT Serif', serif;
    color:#2f2b25;
    font-size:clamp(17px,1.25vw,24px);
    line-height:1.8;
    margin:0 0 clamp(18px,2vw,30px);
}

.gg-about-image{
    grid-column:4 / 5;
    width:100%;
    box-sizing:border-box;
}

.gg-about-image img{
    width:100%;
    height:auto;
    object-fit:contain;
    display:block;
    border:1px solid #9F8560;
}

.gg-about-text a {
    color: #B9965F;
    text-decoration: none;
    font-weight: 500;
    border-bottom: 1px solid rgba(201, 161, 74, 0.4);
}

.gg-about-text a:hover {
    border-bottom-color: #c9a14a;
}

@media(max-width:768px){

    .gg-about-page{
        width:100%;
        padding:40px 4%;
    }

    .gg-about-heading{
        gap:12px;
        margin-bottom:30px;
    }

    .gg-about-heading .gg-small-title{
        font-size:16px;
        letter-spacing:0.18em;
        text-align:center;
    }

    .gg-about-content{

        /* Behåll två kolumner */
        grid-template-columns:58% 42%;

        gap:16px;
        align-items:start;
    }

    .gg-about-text{
        grid-column:auto;
    }

    .gg-about-image{
        grid-column:auto;
    }

    .gg-about-text p{
        font-size:13px;
        line-height:1.6;
        margin-bottom:16px;
    }

    .gg-about-image img{
        width:100%;
        height:auto;
    }
}

</style>
	
	    <?php
    return ob_get_clean();
});

/**
 * Gold Goblins Värdering
 */
add_shortcode('gg_vard', function() {

    if (!function_exists('gg_vard_get_tabs')) {
        return current_user_can('manage_options')
            ? '<p style="padding:40px;text-align:center;">Värdering Hub är inte aktiv. Aktivera hubb-snippeten först.</p>'
            : '';
    }

    $gg_vard_tabs = gg_vard_get_tabs();

    if (empty($gg_vard_tabs) || !is_array($gg_vard_tabs)) {
        return current_user_can('manage_options')
            ? '<p style="padding:40px;text-align:center;">Inga publicerade värderingssektioner finns ännu i Värdering Hub.</p>'
            : '';
    }

    ob_start();
    ?>

<section id="gg-vard-app" class="gg-vard-page">

    <div class="gg-vard-heading">
        <img
            class="gg-vard-heading-image"
            src="https://www.goldgoblins.se/wp-content/uploads/2026/06/9b12-49af-8218-3f9fa75d735a.webp"
            alt=""
            loading="eager"
            decoding="async"
        >

        <h1 class="gg-vard-main-title">
    <span>Värdering av smycken,</span>
    <span>guld och silver i Lidköping</span>
</h1>

        <img
            class="gg-vard-heading-image"
            src="https://www.goldgoblins.se/wp-content/uploads/2026/06/e018b.webp"
            alt=""
            loading="eager"
            decoding="async"
        >
    </div>

    <div class="gg-vard-layout">

        <aside class="gg-vard-menu" aria-label="Värderingstjänster">
            <div class="gg-vard-menu-title">Tjänster</div>

            <div class="gg-vard-tabs" role="tablist" aria-label="Välj värderingstjänst">
                <?php $gg_vard_index = 0; ?>

                <?php foreach ($gg_vard_tabs as $tab_id => $tab) : ?>
                    <?php
                    $safe_tab_id = sanitize_html_class($tab_id);
                    $tab_label = !empty($tab['label']) ? $tab['label'] : 'Sektion';
                    ?>

                    <button
                        type="button"
                        id="gg-vard-tab-<?php echo esc_attr($safe_tab_id); ?>"
                        class="gg-vard-tab <?php echo $gg_vard_index === 0 ? 'is-active' : ''; ?>"
                        role="tab"
                        aria-selected="<?php echo $gg_vard_index === 0 ? 'true' : 'false'; ?>"
                        aria-controls="gg-vard-panel-<?php echo esc_attr($safe_tab_id); ?>"
                        data-tab="<?php echo esc_attr($safe_tab_id); ?>"
                    >
                        <?php echo esc_html($tab_label); ?>
                    </button>

                    <?php $gg_vard_index++; ?>
                <?php endforeach; ?>
            </div>
        </aside>

        <div class="gg-vard-content" aria-live="polite">
            <?php $gg_vard_index = 0; ?>

            <?php foreach ($gg_vard_tabs as $tab_id => $tab) : ?>
                <?php
                $safe_tab_id = sanitize_html_class($tab_id);
                $tab_title = !empty($tab['title']) ? $tab['title'] : (!empty($tab['label']) ? $tab['label'] : '');
                ?>

                <article
                    id="gg-vard-panel-<?php echo esc_attr($safe_tab_id); ?>"
                    class="gg-vard-panel <?php echo $gg_vard_index === 0 ? 'is-active' : ''; ?>"
                    role="tabpanel"
                    aria-labelledby="gg-vard-tab-<?php echo esc_attr($safe_tab_id); ?>"
                    data-panel="<?php echo esc_attr($safe_tab_id); ?>"
                    <?php echo $gg_vard_index === 0 ? '' : 'hidden'; ?>
                >
                    <div class="gg-vard-panel-inner">

                        <?php if (!empty($tab['kicker'])) : ?>
                            <p class="gg-vard-kicker"><?php echo esc_html($tab['kicker']); ?></p>
                        <?php endif; ?>

                        <?php if ($tab_title !== '') : ?>
                            <h2><?php echo esc_html($tab_title); ?></h2>
                        <?php endif; ?>

                        <?php if (!empty($tab['body']) && is_array($tab['body'])) : ?>
                            <?php foreach ($tab['body'] as $paragraph) : ?>
                                <?php if (trim((string) $paragraph) !== '') : ?>
                                    <p><?php echo wp_kses_post($paragraph); ?></p>
                                <?php endif; ?>
                            <?php endforeach; ?>
                        <?php endif; ?>

                        <?php if (!empty($tab['choices']) && is_array($tab['choices'])) : ?>
                            <div class="gg-vard-choice-list">
                                <?php foreach ($tab['choices'] as $choice) : ?>
                                    <?php
                                    $choice_title = $choice['title'] ?? '';
                                    $choice_text = $choice['text'] ?? '';
                                    ?>

                                    <?php if ($choice_title !== '' || $choice_text !== '') : ?>
                                        <div class="gg-vard-choice-row">
                                            <?php if ($choice_title !== '') : ?>
                                                <strong><?php echo esc_html($choice_title); ?></strong>
                                            <?php endif; ?>

                                            <?php if ($choice_text !== '') : ?>
                                                <span><?php echo esc_html($choice_text); ?></span>
                                            <?php endif; ?>
                                        </div>
                                    <?php endif; ?>
                                <?php endforeach; ?>
                            </div>
                        <?php endif; ?>

                        <?php if (!empty($tab['items']) && is_array($tab['items'])) : ?>
                            <div class="gg-vard-price-list">
                                <?php foreach ($tab['items'] as $item) : ?>
                                    <?php
                                    $service = $item['service'] ?? '';
                                    $price = $item['price'] ?? '';
                                    ?>

                                    <?php if ($service !== '' || $price !== '') : ?>
                                        <div class="gg-vard-price-row">
                                            <?php if ($service !== '') : ?>
                                                <span><?php echo esc_html($service); ?></span>
                                            <?php endif; ?>

                                            <?php if ($price !== '') : ?>
                                                <strong><?php echo esc_html($price); ?></strong>
                                            <?php endif; ?>
                                        </div>
                                    <?php endif; ?>
                                <?php endforeach; ?>
                            </div>
                        <?php endif; ?>

                        <?php if (!empty($tab['button']['text']) && !empty($tab['button']['url'])) : ?>
                            <a class="gg-vard-button" href="<?php echo esc_url($tab['button']['url']); ?>">
                                <span class="gg-vard-button-star">✤</span>
                                <span><?php echo esc_html($tab['button']['text']); ?></span>
                                <span class="gg-vard-button-star">✤</span>
                            </a>
                        <?php endif; ?>

                    </div>
                </article>

                <?php $gg_vard_index++; ?>
            <?php endforeach; ?>
        </div>

    </div>

</section>

<style>
.gg-vard-page{
    --gg-vard-bg:#f1dfc4;
    --gg-vard-gold:#B9965F;
    --gg-vard-gold-dark:#9F8560;
    --gg-vard-text:#2f2b25;
    --gg-vard-line:rgba(159,133,96,0.28);

    width:100%;
    position:relative;
    overflow:visible;

    background-color:var(--gg-vard-bg);
    background-image:
        radial-gradient(circle at 18% 12%, rgba(255,255,255,0.12), transparent 28%),
        radial-gradient(circle at 86% 28%, rgba(120,90,55,0.035), transparent 34%),
        radial-gradient(circle at 45% 82%, rgba(255,255,255,0.07), transparent 32%),
        linear-gradient(135deg, rgba(255,255,255,0.035), rgba(120,90,55,0.018));
    background-size:cover;
    background-position:center;

    padding:clamp(42px,4.8vw,82px) 5% clamp(58px,6vw,96px);
    box-sizing:border-box;
}

.gg-vard-heading{
    width:min(920px, 100%);
    margin:0 auto clamp(34px,4vw,62px);
    display:grid;
    grid-template-columns:minmax(70px, 1fr) minmax(0, auto) minmax(70px, 1fr);
    align-items:center;
    gap:clamp(14px,2.4vw,42px);
}

.gg-vard-heading-image{
    width:100%;
    max-width:210px;
    height:auto;
    display:block;
    opacity:0.68;
}

.gg-vard-heading-image:first-child{
    justify-self:end;
}

.gg-vard-heading-image:last-child{
    justify-self:start;
}

.gg-vard-main-title{
    margin:0;
    color:var(--gg-vard-gold);

    font-family:'PT Serif', serif;
    font-size:clamp(30px,3.15vw,52px);
    line-height:0.98;
    letter-spacing:0.13em;
    font-style:italic;
    font-weight:400;
    text-align:center;

    white-space:normal;
}

.gg-vard-main-title span{
    display:block;
    white-space:nowrap;
}

.gg-vard-layout{
    width:min(1060px, 100%);
    margin:0 auto;
    display:grid;
    grid-template-columns:minmax(170px, 205px) minmax(0, 760px);
    gap:clamp(42px,5.4vw,82px);
    align-items:start;
}

.gg-vard-menu{
    position:sticky;
    top:calc(26px + var(--wp-admin--admin-bar--height, 0px));
    align-self:start;

    padding:20px 0;
    border-top:1px solid var(--gg-vard-line);
    border-bottom:1px solid var(--gg-vard-line);
}

.gg-vard-menu-title{
    margin:0 0 19px;
    color:var(--gg-vard-gold);

    font-family:'PT Serif', serif;
    font-size:clamp(11px,0.72vw,13px);
    letter-spacing:0.24em;
    text-transform:uppercase;
    font-weight:400;
}

.gg-vard-tabs{
    display:block;
}

.gg-vard-tab{
    position:relative;
    display:block;
    width:fit-content;
    max-width:100%;

    margin:0 0 13px;
    padding:0;

    border:0;
    background:transparent;
    color:var(--gg-vard-text);

    font-family:'PT Serif', serif;
    font-size:clamp(11px,0.76vw,14px);
    line-height:1.38;
    letter-spacing:0.17em;
    text-transform:uppercase;
    text-align:left;

    cursor:pointer;
    transition:color 0.25s ease;
    z-index:1;
}

.gg-vard-tab::before{
    content:"";
    position:absolute;
    left:50%;
    top:50%;

    width:calc(100% + 20px);
    height:1.65em;

    transform:translate(-50%, -50%) scale(0.72);

    background:radial-gradient(
        ellipse at center,
        rgba(255,255,255,0.76) 0%,
        rgba(255,246,229,0.42) 42%,
        rgba(255,255,255,0) 100%
    );

    border-radius:999px;
    filter:blur(5px);
    opacity:0;

    transition:opacity 0.25s ease, transform 0.25s ease;
    pointer-events:none;
    z-index:-1;
}

.gg-vard-tab:hover,
.gg-vard-tab.is-active{
    color:var(--gg-vard-gold);
}

.gg-vard-tab:hover::before,
.gg-vard-tab.is-active::before{
    opacity:1;
    transform:translate(-50%, -50%) scale(1);
}

.gg-vard-tab:focus-visible{
    outline:1px solid rgba(185,150,95,0.72);
    outline-offset:5px;
}

.gg-vard-content{
    min-height:390px;
    position:relative;
}

.gg-vard-panel{
    opacity:0;
    transform:translateY(5px);
    transition:opacity 0.32s ease, transform 0.32s ease;
}

.gg-vard-panel.is-active{
    opacity:1;
    transform:translateY(0);
}

.gg-vard-panel[hidden]{
    display:none;
}

.gg-vard-panel-inner{
    position:relative;
    isolation:isolate;
    overflow:visible;

    padding:clamp(8px,1.2vw,18px) 0;

    border:0;
    background:transparent;

    -webkit-backdrop-filter:none;
    backdrop-filter:none;

    box-shadow:none;
}

.gg-vard-panel-inner::before{
    display:none;
}

.gg-vard-kicker{
    margin:0 0 17px !important;
    color:var(--gg-vard-gold) !important;

    font-family:'PT Serif', serif;
    font-size:clamp(10px,0.72vw,13px) !important;
    line-height:1.4 !important;
    letter-spacing:0.25em !important;
    text-transform:uppercase;
}

.gg-vard-panel h2{
    max-width:24ch;
    margin:0 0 clamp(18px,1.8vw,24px);

    color:var(--gg-vard-gold);
    font-family:'PT Serif', serif;
    font-size:clamp(25px,1.85vw,32px);
line-height:1.22;
letter-spacing:0.095em;
    font-weight:400;
}

.gg-vard-panel p{
    max-width:56ch;
    margin:0 0 clamp(15px,1.45vw,21px);

    color:var(--gg-vard-text);
    font-family:'PT Serif', serif;
    font-size:clamp(14px,0.96vw,16.5px);
    line-height:1.78;
    letter-spacing:0.042em;
}

.gg-vard-panel a{
    color:var(--gg-vard-gold);
    text-decoration:none;
    border-bottom:1px solid rgba(185,150,95,0.42);
}

.gg-vard-panel a:hover{
    border-bottom-color:var(--gg-vard-gold);
}

.gg-vard-choice-list,
.gg-vard-price-list{
    margin-top:clamp(24px,2.4vw,34px);
    border-top:1px solid rgba(159,133,96,0.34);
}

.gg-vard-choice-row{
    display:grid;
    grid-template-columns:minmax(130px, 0.44fr) minmax(0, 1fr);
    gap:clamp(18px,2.2vw,34px);

    padding:clamp(15px,1.5vw,21px) 0;
    border-bottom:1px solid rgba(159,133,96,0.20);
}

.gg-vard-choice-row strong,
.gg-vard-choice-row span,
.gg-vard-price-row span,
.gg-vard-price-row strong{
    font-family:'PT Serif', serif;
    font-size:clamp(14px,0.92vw,16px);
    line-height:1.62;
    letter-spacing:0.05em;
    font-weight:400;
}

.gg-vard-choice-row strong{
    color:var(--gg-vard-gold);
    letter-spacing:0.08em;
}

.gg-vard-choice-row span{
    color:var(--gg-vard-text);
}

.gg-vard-price-row{
    display:grid;
    grid-template-columns:minmax(0, 1fr) auto;
    gap:clamp(18px,2.2vw,34px);
    align-items:baseline;

    padding:clamp(15px,1.5vw,21px) 0;
    border-bottom:1px solid rgba(159,133,96,0.20);

    transition:border-color 0.25s ease, opacity 0.25s ease;
}
	
	.gg-vard-price-row:hover{
    border-bottom-color:rgba(185,150,95,0.36);
}

.gg-vard-price-row span{
    color:var(--gg-vard-text);
}

.gg-vard-price-row strong{
    color:var(--gg-vard-gold);
    text-align:right;
    white-space:nowrap;
    letter-spacing:0.07em;
    font-variant-numeric:tabular-nums;
}

.gg-vard-button{
    position:relative;
    display:inline-flex;
    align-items:center;
    justify-content:center;
    gap:12px;
    isolation:isolate;
    overflow:hidden;

    margin-top:clamp(18px,2vw,30px);
    padding:10px 20px;

    border:1px solid rgba(185,150,95,0.72) !important;
    color:#3a2c1f !important;
    text-decoration:none !important;

    font-family:Georgia, "Times New Roman", serif;
    font-size:clamp(12px,0.78vw,14px);
    line-height:1.2;
    letter-spacing:0.13em;
    text-transform:uppercase;

    background-color:rgba(241,223,196,0.28);
    background-image:
        linear-gradient(
            180deg,
            rgba(255,255,255,0.42) 0%,
            rgba(255,255,255,0.18) 42%,
            rgba(185,150,95,0.12) 100%
        );

    -webkit-backdrop-filter:blur(10px) saturate(135%);
    backdrop-filter:blur(10px) saturate(135%);

    box-shadow:
    inset 0 1px 0 rgba(255,255,255,0.40),
    inset 0 -1px 0 rgba(120,90,55,0.12),
    0 10px 26px rgba(72,48,24,0.10);

    transition:
        transform 0.25s ease,
        border-color 0.25s ease,
        background-color 0.25s ease,
        box-shadow 0.25s ease,
        color 0.25s ease;
}

.gg-vard-button::before{
    content:"";
    position:absolute;
    inset:0;
    z-index:-1;
    pointer-events:none;

    background:
        radial-gradient(circle at 22% 18%, rgba(255,255,255,0.34), transparent 32%),
        radial-gradient(circle at 82% 78%, rgba(185,150,95,0.22), transparent 36%);
}

.gg-vard-button::after{
    content:"";
    position:absolute;
    left:8%;
    top:0;

    width:84%;
    height:1px;

    pointer-events:none;

    background:linear-gradient(
        90deg,
        transparent,
        rgba(255,255,255,0.72),
        transparent
    );
}

.gg-vard-button:hover{
    transform:translateY(-1px);
    border-color:rgba(196,162,109,0.96) !important;
    background-color:rgba(241,223,196,0.38);

    box-shadow:
        inset 0 1px 0 rgba(255,255,255,0.55),
        inset 0 -1px 0 rgba(120,90,55,0.14),
        0 14px 30px rgba(0,0,0,0.16);
}

.gg-vard-button:focus-visible{
    outline:2px solid rgba(170,138,88,0.55);
    outline-offset:3px;
}

.gg-vard-button:active{
    transform:translateY(0);

    box-shadow:
        inset 0 1px 0 rgba(255,255,255,0.42),
        inset 0 -1px 0 rgba(120,90,55,0.14),
        0 7px 18px rgba(0,0,0,0.10);
}

.gg-vard-button-star{
    color:#aa8a58;
    font-size:0.82em;
    line-height:1;
}

.gg-vard-button span{
    position:relative;
    z-index:1;
}

@media(max-width:900px){

    .gg-vard-page{
        padding:40px 5% 58px;
    }

  

  .gg-vard-heading{
    grid-template-columns:42px minmax(0, 1fr) 42px;
    gap:10px;
    margin-bottom:34px;
}

.gg-vard-heading-image{
    max-width:42px;
    opacity:0.52;
}

.gg-vard-main-title{
    font-size:clamp(25px,7.4vw,38px);
    line-height:1.02;
    letter-spacing:0.055em;
}

.gg-vard-main-title span{
    white-space:normal;
}

    .gg-vard-layout{
        display:block;
        width:100%;
    }

    .gg-vard-menu{
        position:relative;
        top:auto;

        padding:0 0 16px;
        margin:0 0 28px;

        border-top:0;
    }

    .gg-vard-menu-title{
        margin-bottom:12px;
    }

  .gg-vard-tabs{
    display:flex;
    gap:18px;
    overflow-x:auto;
    padding-bottom:8px;
    -webkit-overflow-scrolling:touch;
    scrollbar-width:none;
}

.gg-vard-tabs::-webkit-scrollbar{
    display:none;
}

    .gg-vard-tab{
        flex:0 0 auto;
        margin:0;

        white-space:nowrap;
        font-size:12px;
        letter-spacing:0.12em;
    }

    .gg-vard-content{
        min-height:0;
    }

    .gg-vard-panel-inner{
        padding:28px 22px;
    }

    .gg-vard-panel-inner::before{
        left:22px;
        width:calc(100% - 44px);
    }

   .gg-vard-panel h2{
    max-width:none;
    font-size:clamp(24px,7vw,34px);
    line-height:1.18;
    letter-spacing:0.065em;
}

    .gg-vard-panel p{
        max-width:none;
        font-size:14px;
        line-height:1.65;
        letter-spacing:0.04em;
    }

    .gg-vard-choice-row,
    .gg-vard-price-row{
        grid-template-columns:1fr;
        gap:4px;
    }

    .gg-vard-price-row strong{
        text-align:left;
        white-space:normal;
    }
	
	.gg-vard-price-row{
    padding:16px 0;
}

.gg-vard-price-row span,
.gg-vard-price-row strong{
    line-height:1.5;
}
	
}

@media(max-width:520px){

    .gg-vard-panel-inner{
        border-left:0;
        border-right:0;

        padding-left:0;
        padding-right:0;

        background:transparent;
        box-shadow:none;

        -webkit-backdrop-filter:none;
        backdrop-filter:none;
    }

    .gg-vard-panel-inner::before{
        left:0;
        width:100%;
    }

    .gg-vard-button{
        width:100%;
        box-sizing:border-box;
    }
	
	.gg-vard-heading{
    grid-template-columns:32px minmax(0, 1fr) 32px;
    gap:8px;
}

.gg-vard-heading-image{
    max-width:32px;
    opacity:0.45;
}

.gg-vard-main-title{
    font-size:clamp(23px,8vw,32px);
    line-height:1.05;
    letter-spacing:0.035em;
}
	
}
	
	

@supports not ((backdrop-filter:blur(2px)) or (-webkit-backdrop-filter:blur(2px))){
    .gg-vard-button{
        background-color:rgba(241,223,196,0.82);
    }
}
</style>

<script>
document.addEventListener('DOMContentLoaded', function() {
    const app = document.getElementById('gg-vard-app');

    if (!app) return;

    const tabs = Array.from(app.querySelectorAll('.gg-vard-tab'));
    const panels = Array.from(app.querySelectorAll('.gg-vard-panel'));

    function activateTab(tab) {
        const target = tab.getAttribute('data-tab');

        tabs.forEach(function(item) {
            const isActive = item === tab;

            item.classList.toggle('is-active', isActive);
            item.setAttribute('aria-selected', isActive ? 'true' : 'false');
            item.setAttribute('tabindex', isActive ? '0' : '-1');
        });

        panels.forEach(function(panel) {
            const isActive = panel.getAttribute('data-panel') === target;

            if (isActive) {
                panel.hidden = false;

                requestAnimationFrame(function() {
                    panel.classList.add('is-active');
                });
            } else {
                panel.classList.remove('is-active');
                panel.hidden = true;
            }
        });
    }

    tabs.forEach(function(tab, index) {
        tab.setAttribute('tabindex', index === 0 ? '0' : '-1');

        tab.addEventListener('click', function() {
            activateTab(tab);
        });

        tab.addEventListener('keydown', function(event) {
            const currentIndex = tabs.indexOf(tab);
            let nextIndex = currentIndex;

            if (event.key === 'ArrowDown' || event.key === 'ArrowRight') {
                nextIndex = currentIndex + 1 >= tabs.length ? 0 : currentIndex + 1;
            }

            if (event.key === 'ArrowUp' || event.key === 'ArrowLeft') {
                nextIndex = currentIndex - 1 < 0 ? tabs.length - 1 : currentIndex - 1;
            }

            if (event.key === 'Home') {
                nextIndex = 0;
            }

            if (event.key === 'End') {
                nextIndex = tabs.length - 1;
            }

            if (nextIndex !== currentIndex) {
                event.preventDefault();
                tabs[nextIndex].focus();
                activateTab(tabs[nextIndex]);
            }
        });
    });
});
</script>

    <?php
    return ob_get_clean();
});

/**
 * Gold Goblins Integritetspolicy
 */
add_shortcode('gg_integ', function() {
    ob_start();
    ?>

<section class="gg-privacy-page">

    <div class="gg-privacy-heading">
        <img
            class="gg-privacy-heading-image"
            src="https://www.goldgoblins.se/wp-content/uploads/2026/06/9b12-49af-8218-3f9fa75d735a.webp"
            alt=""
            loading="eager"
            decoding="async"
        >

        <h1>Integritetspolicy</h1>

        <img
            class="gg-privacy-heading-image"
            src="https://www.goldgoblins.se/wp-content/uploads/2026/06/e018b.webp"
            alt=""
            loading="eager"
            decoding="async"
        >
    </div>

    <div class="gg-privacy-intro">
        <p>
            Hos Gold Goblins vill vi att du ska känna dig trygg när du besöker vår webbplats,
            kontaktar oss eller anmäler dig till vårt nyhetsbrev. Vi samlar bara in personuppgifter
            när det behövs för att kunna hjälpa dig, hantera en förfrågan, genomföra ett köp eller
            skicka information som du själv har valt att ta emot.
        </p>

        <p class="gg-privacy-highlight">
            Vi säljer aldrig dina personuppgifter till tredje part.
        </p>
    </div>

    <div class="gg-privacy-content">

        <article class="gg-privacy-card">
            <h2>Vem ansvarar för dina personuppgifter?</h2>
            <p>
                Gold Goblins ansvarar för behandlingen av personuppgifter som samlas in via webbplatsen.
            </p>

            <div class="gg-privacy-contact-box">
                <p><strong>Gold Goblins</strong></p>
                <p>Lidköping, Sverige</p>
                <p>E-post: <a href="mailto:kontakt@goldgoblins.se">kontakt@goldgoblins.se</a></p>
                <p>Organisationsnummer: 969799-8897</p>
            </div>
        </article>

        <article class="gg-privacy-card">
            <h2>Vilka uppgifter kan vi samla in?</h2>
            <p>
                Beroende på hur du använder webbplatsen kan vi behandla följande uppgifter:
            </p>

            <ul>
                <li>Namn</li>
                <li>E-postadress</li>
                <li>Telefonnummer</li>
                <li>Adressuppgifter</li>
                <li>Orderinformation</li>
                <li>Information du själv skriver i kontaktformulär</li>
                <li>E-postadress vid anmälan till nyhetsbrev</li>
                <li>Teknisk information från webbplatsen, till exempel cookies och analysdata</li>
            </ul>

            <p>
                Vi samlar bara in uppgifter som behövs för det aktuella ändamålet.
            </p>
        </article>

        <article class="gg-privacy-card">
            <h2>Nyhetsbrev</h2>
            <p>
                Om du anmäler dig till vårt nyhetsbrev sparar vi din e-postadress,
                tidpunkt för anmälan och att du har lämnat samtycke.
            </p>

            <p>
                Vi använder uppgifterna för att kunna skicka nyhetsbrev, erbjudanden,
                kampanjer och information från Gold Goblins.
            </p>

            <p>
                Den rättsliga grunden är ditt samtycke. Det betyder att du själv väljer om du vill
                anmäla dig, och du kan när som helst ångra dig. Samtycket ska vara frivilligt och
                möjligt att återkalla.
            </p>

            <p>
                Du kan återkalla ditt samtycke genom att kontakta oss på:
            </p>

            <p>
                <a href="mailto:kontakt@goldgoblins.se">kontakt@goldgoblins.se</a>
            </p>

            <p>
                När du återkallar ditt samtycke tar vi bort din e-postadress från vår nyhetsbrevslista,
                om vi inte behöver spara uppgiften av annan laglig anledning.
            </p>
        </article>

        <article class="gg-privacy-card">
            <h2>Kontaktformulär och kundservice</h2>
            <p>
                När du kontaktar oss via formulär eller e-post behandlar vi de uppgifter du själv lämnar,
                till exempel namn, e-postadress, telefonnummer och meddelande.
            </p>

            <p>
                Vi använder uppgifterna för att kunna svara på din fråga, hjälpa dig med ett ärende eller
                hantera en förfrågan om exempelvis smycken, specialbeställningar, värdering, leverans,
                retur eller reklamation.
            </p>
        </article>

        <article class="gg-privacy-card">
            <h2>Köp och beställningar</h2>
            <p>
                När du handlar hos Gold Goblins behandlas de uppgifter som behövs för att kunna hantera
                din beställning, ta betalt, skicka varan, hantera returer och uppfylla bokföringskrav.
            </p>

            <p>
                Det kan till exempel vara namn, adress, e-postadress, telefonnummer, orderinformation
                och betalningsrelaterad information.
            </p>
        </article>

        <article class="gg-privacy-card gg-privacy-optout-card">
            <h2>Cookies och analys</h2>
            <p>
                Vår webbplats kan använda cookies och liknande tekniker för att webbplatsen ska fungera,
                förbättra användarupplevelsen och hjälpa oss förstå hur webbplatsen används.
            </p>

            <p>
                Om vi använder Google Analytics eller liknande analystjänster kan information om hur
                besökare använder webbplatsen samlas in i anonymiserad eller aggregerad form. Det hjälper
                oss att se vilka sidor som fungerar bra, vilka sidor som behöver förbättras och hur vi kan
                göra webbplatsen snabbare, tydligare och mer användarvänlig.
            </p>

            <p>
                Du ska kunna använda webbplatsen även om du inte vill bidra till analysdata. Du kan därför
                blockera eller radera cookies i din webbläsare. Om webbplatsen använder Google Analytics
                kan du även välja att installera Googles officiella webbläsartillägg för bortval av
                Google Analytics.
            </p>

            <div class="gg-privacy-optout-box">
                <h3>Google Analytics opt-out</h3>

                <p>
                    Googles tillägg gör att du kan förhindra att din besöksdata används av Google Analytics
                    på webbplatser som använder stödda versioner av Google Analytics JavaScript.
                </p>

                <p>
                    Det kan vara en fördel om du vill minska mängden analysdata som skickas till Google
                    Analytics när du besöker webbplatser. Det påverkar normalt inte möjligheten att använda
                    Gold Goblins webbplats, handla, läsa information eller kontakta oss.
                </p>

                <a
                    class="gg-privacy-optout-button"
                    href="https://tools.google.com/dlpage/gaoptout"
                    target="_blank"
                    rel="noopener noreferrer"
                >
                    Ladda ned Google Analytics opt-out
                </a>
            </div>
        </article>

        <article class="gg-privacy-card">
            <h2>Hur länge sparar vi uppgifterna?</h2>
            <p>
                Vi sparar personuppgifter så länge det behövs för ändamålet.
            </p>

            <p>
                Nyhetsbrevsuppgifter sparas så länge du vill få nyhetsbrev från oss. Om du återkallar
                ditt samtycke tar vi bort dig från listan.
            </p>

            <p>
                Uppgifter kopplade till köp och betalning kan behöva sparas längre för att uppfylla
                bokföringskrav, hantera garantiärenden, reklamationer eller andra rättsliga skyldigheter.
            </p>

            <p>
                Kontaktärenden sparas så länge det behövs för att kunna hantera ärendet och följa upp
                kommunikationen.
            </p>
        </article>

        <article class="gg-privacy-card">
            <h2>Dina rättigheter</h2>
            <p>
                Du har rätt att få information om vilka personuppgifter vi behandlar om dig. Du kan också
                begära att uppgifter rättas, raderas eller begränsas.
            </p>

            <p>Du kan när som helst kontakta oss om du vill:</p>

            <ul>
                <li>Få veta vilka uppgifter vi har om dig</li>
                <li>Rätta felaktiga uppgifter</li>
                <li>Be oss radera uppgifter</li>
                <li>Återkalla samtycke till nyhetsbrev</li>
                <li>Invända mot viss behandling</li>
            </ul>

            <p>
                Kontakta oss på:
                <a href="mailto:kontakt@goldgoblins.se">kontakt@goldgoblins.se</a>
            </p>
        </article>

        <article class="gg-privacy-card">
            <h2>Tredje parter</h2>
            <p>
                Vi kan använda externa tjänster för exempelvis webbhotell, betalningar, leverans, analys,
                e-post och teknisk drift. Dessa aktörer får bara behandla personuppgifter i den utsträckning
                det behövs för att deras tjänster ska fungera.
            </p>

            <p>
                Vi säljer aldrig dina personuppgifter.
            </p>
        </article>

        <article class="gg-privacy-card">
            <h2>Ändringar i denna policy</h2>
            <p>
                Vi kan uppdatera denna integritetspolicy om webbplatsen, våra tjänster eller lagkrav
                förändras. Den senaste versionen finns alltid på denna sida.
            </p>

            <p class="gg-privacy-updated">
                Senast uppdaterad: 30 juni 2026
            </p>
        </article>

    </div>

</section>

<style>
.gg-privacy-page{
    width:100%;
    background-color:#f1dfc4;
    background-image:
        radial-gradient(circle at 20% 10%, rgba(255,255,255,0.18), transparent 28%),
        radial-gradient(circle at 85% 35%, rgba(120,90,55,0.05), transparent 35%),
        linear-gradient(135deg, rgba(255,255,255,0.05), rgba(120,90,55,0.03));
    border-top:3px solid #9F8560;
    border-bottom:3px solid #9F8560;
    padding:clamp(50px,6vw,110px) 5%;
    box-sizing:border-box;
}

.gg-privacy-heading{
    max-width:980px;
    margin:0 auto clamp(34px,4vw,70px);
    display:grid;
    grid-template-columns:1fr auto 1fr;
    align-items:center;
    gap:clamp(16px,3vw,55px);
}

.gg-privacy-heading h1{
    margin:0;
    color:#B9965F;
    font-family:'PT Serif', serif;
    font-size:clamp(28px,4vw,62px);
    letter-spacing:0.11em;
    white-space:nowrap;
    font-style:italic;
    font-weight:400;
    line-height:1.2;
    text-align:center;
}

.gg-privacy-heading-image{
    width:100%;
    height:auto;
    display:block;
}

.gg-privacy-intro{
    max-width:920px;
    margin:0 auto clamp(34px,4vw,70px);
    text-align:center;
}

.gg-privacy-intro p,
.gg-privacy-card p,
.gg-privacy-card li{
    font-family:'PT Serif', serif;
    color:#2f2b25;
    font-size:clamp(16px,1.15vw,22px);
    line-height:1.8;
    letter-spacing:0.055em;
}

.gg-privacy-intro p{
    margin:0 0 clamp(18px,2vw,28px);
}

.gg-privacy-highlight{
    display:inline-block;
    color:#9F8560 !important;
    border-top:1px solid rgba(159,133,96,0.55);
    border-bottom:1px solid rgba(159,133,96,0.55);
    padding:14px 22px;
    margin-top:10px !important;
}

.gg-privacy-content{
    max-width:1040px;
    margin:0 auto;
    display:flex;
    flex-direction:column;
    gap:clamp(22px,2.6vw,42px);
}

.gg-privacy-card{
    background:rgba(255,248,235,0.44);
    border:1px solid rgba(159,133,96,0.35);
    box-shadow:0 14px 36px rgba(47,43,37,0.06);
    padding:clamp(24px,3vw,48px);
    box-sizing:border-box;
}

.gg-privacy-card h2{
    margin:0 0 clamp(16px,1.8vw,28px);
    color:#B9965F;
    font-family:'PT Serif', serif;
    font-size:clamp(21px,2vw,34px);
    line-height:1.35;
    letter-spacing:0.11em;
    font-weight:400;
}

.gg-privacy-card h3{
    margin:0 0 14px;
    color:#9F8560;
    font-family:'PT Serif', serif;
    font-size:clamp(18px,1.5vw,26px);
    line-height:1.35;
    letter-spacing:0.09em;
    font-weight:400;
}

.gg-privacy-card p{
    margin:0 0 clamp(16px,1.8vw,26px);
}

.gg-privacy-card p:last-child{
    margin-bottom:0;
}

.gg-privacy-card ul{
    margin:0 0 clamp(18px,2vw,28px);
    padding-left:1.3em;
}

.gg-privacy-card li{
    margin:0 0 8px;
    padding-left:0.25em;
}

.gg-privacy-card a{
    color:#9F8560;
    text-decoration:none;
    border-bottom:1px solid rgba(159,133,96,0.45);
    transition:color 0.25s ease, border-color 0.25s ease;
}

.gg-privacy-card a:hover{
    color:#B9965F;
    border-bottom-color:#B9965F;
}

.gg-privacy-contact-box{
    background:rgba(47,43,37,0.05);
    border-left:3px solid #B9965F;
    padding:18px 22px;
    margin-top:18px;
}

.gg-privacy-contact-box p{
    margin:0 0 8px;
}

.gg-privacy-contact-box p:last-child{
    margin-bottom:0;
}

.gg-privacy-optout-card{
    position:relative;
    overflow:hidden;
}

.gg-privacy-optout-box{
    margin-top:clamp(22px,2.4vw,38px);
    padding:clamp(22px,2.8vw,42px);
    background-image:
        linear-gradient(rgba(47,43,37,0.33), rgba(47,43,37,0.33)),
        url("https://www.goldgoblins.se/wp-content/uploads/2026/06/Gold_Goblins_marmor.webp");
    background-size:cover;
    background-position:center;
    border:1px solid rgba(185,150,95,0.65);
    box-shadow:0 18px 44px rgba(47,43,37,0.18);
}

.gg-privacy-optout-box h3,
.gg-privacy-optout-box p{
    color:#f4f1ec;
}

.gg-privacy-optout-box h3{
    color:#B9965F;
}

.gg-privacy-optout-button{
    display:inline-flex;
    align-items:center;
    justify-content:center;
    min-height:48px;
    margin-top:8px;
    padding:13px 24px;
    border:1px solid #B9965F !important;
    background:transparent;
    color:#B9965F !important;
    font-family:'PT Serif', serif;
    font-size:clamp(13px,0.95vw,17px);
    line-height:1.35;
    letter-spacing:0.08em;
    text-decoration:none !important;
    transition:background 0.25s ease, color 0.25s ease, transform 0.25s ease;
}

.gg-privacy-optout-button:hover{
    background:#B9965F;
    color:#2f2b25 !important;
    transform:translateY(-1px);
}

.gg-privacy-updated{
    color:#9F8560 !important;
    font-style:italic;
}

@media(max-width:768px){
    .gg-privacy-page{
        padding:42px 5%;
    }

    .gg-privacy-heading{
        gap:12px;
        margin-bottom:30px;
    }

    .gg-privacy-heading h1{
        font-size:clamp(25px,8vw,38px);
        letter-spacing:0.07em;
    }

    .gg-privacy-intro{
        text-align:left;
    }

    .gg-privacy-intro p,
    .gg-privacy-card p,
    .gg-privacy-card li{
        font-size:14px;
        line-height:1.7;
        letter-spacing:0.035em;
    }

    .gg-privacy-card{
        padding:24px 18px;
    }

    .gg-privacy-card h2{
        font-size:clamp(19px,6vw,27px);
        letter-spacing:0.07em;
    }

    .gg-privacy-card h3{
        font-size:clamp(17px,5vw,23px);
        letter-spacing:0.06em;
    }

    .gg-privacy-optout-box{
        padding:24px 18px;
    }

    .gg-privacy-optout-button{
        width:100%;
        text-align:center;
        padding:13px 16px;
    }
}
</style>

    <?php
    return ob_get_clean();
});

/**
 * Gold Goblins Kontakta Oss
 */
add_action('init', function() {

    register_post_type('gg_contact_message', [
        'labels' => [
            'name'          => 'Kontaktmeddelanden',
            'singular_name' => 'Kontaktmeddelande',
            'menu_name'     => 'Kontaktmeddelanden',
            'add_new_item'  => 'Lägg till meddelande',
            'edit_item'     => 'Visa meddelande',
        ],
        'public'       => false,
        'show_ui'      => true,
        'show_in_menu' => true,
        'supports'     => ['title', 'editor'],
        'menu_icon'    => 'dashicons-email',
    ]);

});


add_action('wp_ajax_gg_contact_message', 'gg_handle_contact_message');
add_action('wp_ajax_nopriv_gg_contact_message', 'gg_handle_contact_message');

function gg_handle_contact_message() {

    if (
        empty($_POST['nonce']) ||
        !wp_verify_nonce(sanitize_text_field(wp_unslash($_POST['nonce'])), 'gg_contact_message')
    ) {
        wp_send_json_error([
            'message' => 'Säkerhetskontrollen misslyckades. Ladda om sidan och försök igen.',
        ], 403);
    }

    if (!empty($_POST['website'])) {
        wp_send_json_success([
            'message' => 'Tack! Ditt meddelande har skickats.',
        ]);
    }

    $name = isset($_POST['name'])
        ? sanitize_text_field(wp_unslash($_POST['name']))
        : '';

    $email = isset($_POST['email'])
        ? sanitize_email(wp_unslash($_POST['email']))
        : '';

    $subject = isset($_POST['subject'])
        ? sanitize_text_field(wp_unslash($_POST['subject']))
        : '';

    $message = isset($_POST['message'])
        ? sanitize_textarea_field(wp_unslash($_POST['message']))
        : '';

    if (!$name || !$email || !$message) {
        wp_send_json_error([
            'message' => 'Fyll i namn, e-post och meddelande.',
        ], 400);
    }

    if (!is_email($email)) {
        wp_send_json_error([
            'message' => 'Ange en giltig e-postadress.',
        ], 400);
    }

    if (!$subject) {
        $subject = 'Kontakt via Gold Goblins';
    }

    $post_title = sprintf(
        '%s – %s',
        $name,
        current_time('Y-m-d H:i')
    );

    $post_content =
        "Namn: {$name}\n" .
        "E-post: {$email}\n" .
        "Ämne: {$subject}\n\n" .
        "Meddelande:\n{$message}";

    $post_id = wp_insert_post([
        'post_type'    => 'gg_contact_message',
        'post_status'  => 'private',
        'post_title'   => $post_title,
        'post_content' => $post_content,
    ], true);

    if (is_wp_error($post_id)) {
        wp_send_json_error([
            'message' => 'Meddelandet kunde inte sparas. Försök igen senare.',
        ], 500);
    }

    update_post_meta($post_id, '_gg_contact_name', $name);
    update_post_meta($post_id, '_gg_contact_email', $email);
    update_post_meta($post_id, '_gg_contact_subject', $subject);
    update_post_meta($post_id, '_gg_contact_date', current_time('mysql'));

    $to = 'kontakt@goldgoblins.se';

    $mail_subject = 'Nytt kontaktmeddelande från Gold Goblins';

    $mail_body =
        "Du har fått ett nytt kontaktmeddelande via goldgoblins.se.\n\n" .
        "Namn: {$name}\n" .
        "E-post: {$email}\n" .
        "Ämne: {$subject}\n\n" .
        "Meddelande:\n{$message}\n\n" .
        "Meddelandet finns även sparat i WordPress-admin under Kontaktmeddelanden.";

    $headers = [
        'Content-Type: text/plain; charset=UTF-8',
        'Reply-To: ' . $name . ' <' . $email . '>',
    ];

    wp_mail($to, $mail_subject, $mail_body, $headers);

    wp_send_json_success([
        'message' => 'Tack! Ditt meddelande har skickats. Vi återkommer så snart vi kan.',
    ]);
}

add_shortcode('gg_kontakt', function() {
    ob_start();
    ?>

<section class="gg-contact-header">

    <h1>KONTAKTA OSS</h1>

    <div class="gg-contact-divider">
        <img
            src="https://www.goldgoblins.se/wp-content/uploads/2026/06/e01we3r5y6tyjggretgh-1.webp"
            alt=""
            loading="eager"
            decoding="async"
        >
    </div>

    <p>
        Har du frågor om ett smycke, en specialbeställning,
        storlek, leverans eller skötsel?<br>
        Vi hjälper dig gärna.
    </p>

</section>


<section class="gg-info-page">

    <div class="gg-info-heading">
        <img
            class="gg-heading-image"
            src="https://www.goldgoblins.se/wp-content/uploads/2026/06/9b12-49af-8218-3f9fa75d735a.webp"
            alt=""
            loading="eager"
            decoding="async"
        >

        <h2 class="gg-small-title gg-info-title">VANLIGA FRÅGOR</h2>

        <img
            class="gg-heading-image"
            src="https://www.goldgoblins.se/wp-content/uploads/2026/06/e018b.webp"
            alt=""
            loading="eager"
            decoding="async"
        >
    </div>

    <div class="gg-info-content">

        <div id="faq" class="gg-info-block">

            <h3>Är era smycken handgjorda?</h3>
            <p>Ja, många av våra smycken tillverkas för hand i vår verkstad med fokus på kvalitet, hantverk och hållbarhet.</p>

            <h3>Vilka material använder ni?</h3>
            <p>Gold Goblins arbetar bland annat med silver, guld och andra ädelmetaller. Vi kan även återbruka kundens egna metaller vid särskilda uppdrag.</p>

            <h3>Kan jag beställa ett specialdesignat smycke?</h3>
            <p>Ja, vi erbjuder specialbeställningar och skräddarsydda lösningar. Kontakta oss gärna för att diskutera dina idéer, material och pris.</p>

            <h3>Hur sköter jag mitt smycke?</h3>
            <p>För bästa hållbarhet rekommenderar vi att du förvarar smycket torrt, undviker starka kemikalier och rengör det regelbundet med lämpliga produkter för ädelmetaller.</p>

            <h3>Hur hittar jag rätt ringstorlek?</h3>
            <p>För att hitta rätt storlek rekommenderar vi att du använder vår storleksguide för ringar, där du hittar instruktioner för mätning och storlekstabeller.</p>

            <h3>Vilken längd ska jag välja på mitt halsband?</h3>
            <p>Valet av halsbandslängd är individuellt och beror på önskad passform. Se vår storleksguide för halsband för att jämföra olika längder och hitta den som passar dig bäst.</p>

            <h3>Erbjuder ni värdering av smycken?</h3>
            <p>Ja, Gold Goblins erbjuder värdering av smycken, guld, silver, platina och andra ädelmetaller. Värderingen kan användas vid exempelvis försäkring, arvskifte, försäljning eller dokumentation.</p>

            <h3>Hur kontaktar jag er?</h3>
            <p>Du kan kontakta oss via vårt kontaktformulär eller via e-post. Vi svarar normalt inom 1–3 arbetsdagar.</p>

        </div>

        <div id="leverans" class="gg-info-block">

            <div class="gg-info-heading gg-info-subheading">
                <img class="gg-heading-image" src="https://www.goldgoblins.se/wp-content/uploads/2026/06/9b12-49af-8218-3f9fa75d735a.webp" alt="" loading="lazy" decoding="async">
                <h2 class="gg-small-title gg-info-title">FRAKT &amp; LEVERANS</h2>
                <img class="gg-heading-image" src="https://www.goldgoblins.se/wp-content/uploads/2026/06/e018b.webp" alt="" loading="lazy" decoding="async">
            </div>

            <h3>Hur lång är leveranstiden?</h3>
            <p>Leveranstiden varierar beroende på produkt och aktuell arbetsbelastning. Vi tillverkar många av våra smycken för hand, vilket innebär att vissa beställningar kan ta lite längre tid. Normal leveranstid är vanligtvis några arbetsdagar upp till två veckor. Maximal leveranstid är 14 dagar från beställningstillfället.</p>

            <h3>Vad kostar frakten?</h3>
            <p>Vi erbjuder gratis frakt på alla beställningar över 1 000 kr. För beställningar under detta belopp tillkommer fraktkostnad enligt aktuell prislista i kassan.</p>

            <h3>Kan jag spåra min beställning?</h3>
            <p>Ja, när din beställning skickas får du en leveransbekräftelse med spårningsinformation om vald fraktmetod erbjuder detta.</p>

            <h3>Levererar ni internationellt?</h3>
            <p>Nej, för närvarande levererar vi endast inom Sverige.</p>

        </div>

        <div id="retur" class="gg-info-block">

            <div class="gg-info-heading gg-info-subheading">
                <img class="gg-heading-image" src="https://www.goldgoblins.se/wp-content/uploads/2026/06/9b12-49af-8218-3f9fa75d735a.webp" alt="" loading="lazy" decoding="async">
                <h2 class="gg-small-title gg-info-title">RETUR &amp; ÅNGERRÄTT</h2>
                <img class="gg-heading-image" src="https://www.goldgoblins.se/wp-content/uploads/2026/06/e018b.webp" alt="" loading="lazy" decoding="async">
            </div>

            <h3>Kan jag returnera en vara?</h3>
            <p>Ja, som privatkund har du enligt svensk lag 14 dagars ångerrätt från det att du mottagit din beställning.</p>

            <h3>Vilka villkor gäller för retur?</h3>
            <p>Produkten ska returneras i oförändrat skick och i originalförpackning. Kunden ansvarar för returfrakten om inget annat avtalats.</p>

            <h3>Kan jag returnera specialtillverkade produkter?</h3>
            <p>Nej, ångerrätten gäller normalt inte för specialbeställda, personligt anpassade eller graverade produkter som tillverkats specifikt efter kundens önskemål.</p>

        </div>

        <div id="reklamation" class="gg-info-block">

            <div class="gg-info-heading gg-info-subheading">
                <img class="gg-heading-image" src="https://www.goldgoblins.se/wp-content/uploads/2026/06/9b12-49af-8218-3f9fa75d735a.webp" alt="" loading="lazy" decoding="async">
                <h2 class="gg-small-title gg-info-title">REKLAMATION</h2>
                <img class="gg-heading-image" src="https://www.goldgoblins.se/wp-content/uploads/2026/06/e018b.webp" alt="" loading="lazy" decoding="async">
            </div>

            <h3>Vad gör jag om min vara är skadad eller felaktig?</h3>
            <p>Kontakta oss så snart som möjligt efter att felet upptäckts. Skicka gärna med bilder och en beskrivning av problemet så hjälper vi dig vidare.</p>

            <h3>Hur lång reklamationsrätt har jag?</h3>
            <p>Som konsument har du reklamationsrätt enligt gällande svensk konsumentlagstiftning.</p>

            <h3>Vem betalar frakten vid en godkänd reklamation?</h3>
            <p>Om reklamationen godkänns står vi självklart för samtliga kostnader kopplade till reklamationen, inklusive frakt.</p>

        </div>

        <div id="besok" class="gg-info-block gg-visit-block">

            <div class="gg-info-heading gg-info-subheading">
                <img class="gg-heading-image" src="https://www.goldgoblins.se/wp-content/uploads/2026/06/9b12-49af-8218-3f9fa75d735a.webp" alt="" loading="lazy" decoding="async">
                <h2 class="gg-small-title gg-info-title">BESÖK VÅR VERKSTAD</h2>
                <img class="gg-heading-image" src="https://www.goldgoblins.se/wp-content/uploads/2026/06/e018b.webp" alt="" loading="lazy" decoding="async">
            </div>

            <h3>Vill du besöka vår smyckesverkstad i Lidköping?</h3>

            <p>
                Hör gärna av dig i förväg så bokar vi en tid som passar.
                Vi tar emot besök enligt överenskommelse för smycken, specialbeställningar, värdering och återbruk av ädelmetaller.
            </p>

        </div>

    </div>

</section>


<section class="gg-contact-page">

    <div class="gg-contact-left">

        <h3>KONTAKTA OSS</h3>

        <p>
            Vi finns här för att hjälpa dig. Oavsett om du har frågor om en produkt,
            behöver hjälp med en beställning eller vill diskutera en specialbeställning,
            är du varmt välkommen att höra av dig.
        </p>

        <p>Vi svarar vanligtvis inom 1–3 arbetsdagar.</p>

        <p>Tack för att du är en del av Gold Goblins.</p>

        <div class="gg-contact-ornament">
            <img src="https://www.goldgoblins.se/wp-content/uploads/2026/06/e01we3r5y6tyjggretgh-1.webp" alt="" loading="lazy" decoding="async">
        </div>

        <div class="gg-contact-info">
            <img src="https://www.goldgoblins.se/wp-content/uploads/2026/06/213RWEEEWFSD1.png" alt="" loading="lazy" decoding="async">
            <div>
                <span>E-POST</span>
                <strong>KONTAKT@GOLDGOBLINS.SE</strong>
            </div>
        </div>

        <div class="gg-contact-info">
            <img src="https://www.goldgoblins.se/wp-content/uploads/2026/06/213RWEEEWFSD2.png" alt="" loading="lazy" decoding="async">
            <div>
                <span>PLATS</span>
                <strong>LIDKÖPING, SVERIGE</strong>
            </div>
        </div>

        <div class="gg-contact-info">
            <img src="https://www.goldgoblins.se/wp-content/uploads/2026/06/213RWEEEWFSD3.png" alt="" loading="lazy" decoding="async">
            <div>
                <span>SPECIALBESTÄLLNINGAR</span>
                <strong>VÄLKOMMEN ATT KONTAKTA OSS FÖR UNIKA SMYCKEN.</strong>
            </div>
        </div>

    </div>

    <div id="kontaktformular" class="gg-contact-right">

        <div class="gg-form-title-row">
            <span>FORMULÄR</span>
            <img src="https://www.goldgoblins.se/wp-content/uploads/2026/06/e018b.webp" alt="" loading="lazy" decoding="async">
        </div>

        <h2>Skicka ett meddelande.</h2>

        <p>
            Fyll i formuläret så återkommer vi så snart vi kan.
        </p>

       <form class="gg-contact-form" action="#" method="post">
    <label for="gg-contact-name">Namn *</label>
    <input id="gg-contact-name" type="text" name="name" autocomplete="name" required>

    <label for="gg-contact-email">E-post *</label>
    <input id="gg-contact-email" type="email" name="email" autocomplete="email" required>

    <label for="gg-contact-message">Meddelande *</label>
    <textarea id="gg-contact-message" name="message" required></textarea>

    <label for="gg-contact-subject">Ämne</label>
    <input id="gg-contact-subject" type="text" name="subject">

    <input
        type="text"
        name="website"
        class="gg-contact-website"
        tabindex="-1"
        autocomplete="off"
        aria-hidden="true"
    >

    <input
        type="hidden"
        name="gg_contact_nonce"
        value="<?php echo esc_attr(wp_create_nonce('gg_contact_message')); ?>"
    >

    <button type="submit">SKICKA</button>

    <p class="gg-contact-message" aria-live="polite"></p>
</form>

        <p class="gg-form-note">
            Genom att skicka formuläret godkänner du att vi använder dina uppgifter
            för att besvara din förfrågan. Läs mer i vår
            <a href="https://www.goldgoblins.se/integritetspolicy/">integritetspolicy</a>.
        </p>

    </div>

</section>


<style>
.gg-contact-header,
.gg-info-page,
.gg-contact-page{
    background-color:#f1dfc4;
    background-image:
        radial-gradient(circle at 20% 15%, rgba(255,255,255,0.10), transparent 30%),
        radial-gradient(circle at 80% 35%, rgba(120,90,55,0.03), transparent 35%),
        radial-gradient(circle at 45% 80%, rgba(255,255,255,0.06), transparent 30%),
        linear-gradient(135deg, rgba(255,255,255,0.03), rgba(120,90,55,0.02));
    background-size:cover;
    background-position:center;
    box-sizing:border-box;
}

.gg-contact-header{
    width:100%;
    text-align:center;
    padding:clamp(60px,6vw,120px) 5% clamp(50px,5vw,90px);
}

.gg-contact-header h1{
    margin:0;
    color:#2f2b25;
    font-family:'PT Serif', serif;
    font-size:clamp(42px,5vw,92px);
    font-weight:400;
    letter-spacing:0.18em;
}

.gg-contact-divider{
    margin:clamp(20px,2vw,35px) auto;
}

.gg-contact-divider img{
    width:clamp(120px,12vw,260px);
    height:auto;
    display:block;
    margin:auto;
}

.gg-contact-header p{
    max-width:900px;
    margin:0 auto;
    color:#2f2b25;
    font-family:'PT Serif', serif;
    font-size:clamp(18px,1.3vw,28px);
    line-height:1.7;
    letter-spacing:0.08em;
}

.gg-info-page{
    position:relative;
    width:100%;
    padding:clamp(50px,6vw,110px) 5%;
    border-top:0;
    border-bottom:0;
}

	.gg-info-page::before,
.gg-info-page::after{
    content:"";
    position:absolute;
    left:0;
    right:0;
    height:1px;

    background:linear-gradient(
        90deg,
        transparent 0%,
        rgba(159,133,96,0.28) 18%,
        rgba(159,133,96,0.70) 50%,
        rgba(159,133,96,0.28) 82%,
        transparent 100%
    );

    pointer-events:none;
}

.gg-info-page::before{
    top:0;
}

.gg-info-page::after{
    bottom:0;
}
	
.gg-info-heading{
    max-width:950px;
    margin:0 auto clamp(40px,4vw,70px);
    display:grid;
    grid-template-columns:1fr auto 1fr;
    align-items:center;
    gap:clamp(20px,3vw,60px);
}

.gg-info-subheading{
    margin-bottom:clamp(28px,3vw,50px);
}

.gg-heading-image{
    width:100%;
    height:auto;
    display:block;
}

.gg-info-heading .gg-small-title{
    margin:0;
    color:#B9965F;
    font-family:'PT Serif', serif;
    font-size:clamp(18px,2.2vw,32px);
    line-height:1.3;
    letter-spacing:0.28em;
    white-space:nowrap;
    font-weight:400;
    text-align:center;
}

.gg-info-content{
    max-width:1100px;
    margin:0 auto;
}

.gg-info-block{
    position:relative;
    scroll-margin-top:120px;
    margin-bottom:clamp(45px,5vw,80px);
    padding-bottom:clamp(35px,4vw,60px);
    border-bottom:0;
}

	.gg-info-block::after{
    content:"";
    position:absolute;
    left:8%;
    right:8%;
    bottom:0;
    height:1px;

    background:linear-gradient(
        90deg,
        transparent 0%,
        rgba(159,133,96,0.18) 12%,
        rgba(159,133,96,0.48) 50%,
        rgba(159,133,96,0.18) 88%,
        transparent 100%
    );

    pointer-events:none;
}

.gg-info-block:last-child::after{
    display:none;
}
	
.gg-info-block:last-child{
    border-bottom:none;
    margin-bottom:0;
    padding-bottom:0;
}

.gg-info-block h3{
    font-family:'PT Serif', serif;
    color:#2f2b25;
    font-size:clamp(19px,1.6vw,28px);
    line-height:1.45;
    letter-spacing:0.04em;
    margin:clamp(22px,2vw,34px) 0 8px;
    font-weight:400;
}

.gg-info-block p{
    font-family:'PT Serif', serif;
    color:#2f2b25;
    font-size:clamp(17px,1.25vw,23px);
    line-height:1.8;
    letter-spacing:0.055em;
    margin:0 0 clamp(14px,1.6vw,24px);
}

.gg-visit-block{
    text-align:center;
}

.gg-visit-block p{
    max-width:850px;
    margin-left:auto;
    margin-right:auto;
}

.gg-contact-page{
    position:relative;
    width:100%;
    display:grid;
    grid-template-columns:35% 65%;
    border-bottom:0;
}

	.gg-contact-page::after{
    content:"";
    position:absolute;
    left:0;
    right:0;
    bottom:0;
    height:1px;

    background:linear-gradient(
        90deg,
        transparent 0%,
        rgba(159,133,96,0.28) 18%,
        rgba(159,133,96,0.70) 50%,
        rgba(159,133,96,0.28) 82%,
        transparent 100%
    );

    pointer-events:none;
    z-index:5;
}
	
.gg-contact-left{
    background-image:
        linear-gradient(rgba(47,43,37,0.18), rgba(47,43,37,0.18)),
        url("https://www.goldgoblins.se/wp-content/uploads/2026/06/Gold_Goblins_marmor.webp");
    background-size:cover;
    background-position:center;
    padding:clamp(45px,5vw,90px);
    box-sizing:border-box;
    color:#f4f1ec;
}

.gg-contact-left h3{
    color:#B9965F;
    font-family:'PT Serif', serif;
    font-size:clamp(18px,1.8vw,32px);
    letter-spacing:0.35em;
    margin:0 0 clamp(40px,4vw,70px);
}

.gg-contact-left p{
    font-family:'PT Serif', serif;
    font-size:clamp(15px,1.1vw,21px);
    line-height:1.8;
    letter-spacing:0.12em;
    margin:0 0 clamp(25px,3vw,45px);
}

.gg-contact-ornament{
    text-align:center;
    margin:clamp(30px,4vw,70px) 0;
}

.gg-contact-ornament img{
    width:clamp(120px,12vw,240px);
    height:auto;
}

.gg-contact-info{
    display:grid;
    grid-template-columns:clamp(45px,4vw,80px) 1fr;
    gap:20px;
    align-items:center;
    margin-top:clamp(25px,3vw,50px);
}

.gg-contact-info img{
    width:100%;
    height:auto;
}

.gg-contact-info span{
    display:block;
    color:#B9965F;
    font-family:'PT Serif', serif;
    letter-spacing:0.25em;
}

.gg-contact-info strong{
    display:block;
    color:#f4f1ec;
    font-family:'PT Serif', serif;
    letter-spacing:0.12em;
    font-size:clamp(12px,0.9vw,17px);
}

.gg-contact-right{
    padding:clamp(45px,5vw,90px);
    box-sizing:border-box;
}

.gg-form-title-row{
    display:flex;
    align-items:center;
    gap:20px;
    margin-bottom:25px;
}

.gg-form-title-row span{
    color:#B9965F;
    font-family:'PT Serif', serif;
    font-size:clamp(18px,1.8vw,32px);
    letter-spacing:0.35em;
    white-space:nowrap;
}

.gg-form-title-row img{
    width:clamp(140px,18vw,340px);
    max-width:none;
    height:auto;
    display:block;
    flex:none;
}

.gg-contact-right h2{
    font-family:'PT Serif', serif;
    color:#2f2b25;
    font-size:clamp(32px,3vw,60px);
    letter-spacing:0.18em;
    font-weight:400;
    margin:0 0 20px;
}

.gg-contact-right p,
.gg-contact-form label{
    font-family:'PT Serif', serif;
    color:#2f2b25;
    font-size:clamp(15px,1.1vw,21px);
    letter-spacing:0.08em;
    line-height:1.6;
}

.gg-contact-form{
    max-width:620px;
}

.gg-contact-form input,
.gg-contact-form textarea{
    width:100%;
    background:rgba(241,223,196,0.18);
    border:1px solid rgba(159,133,96,0.55);
    padding:14px;
    box-sizing:border-box;
    margin:8px 0 22px;
    font-family:'PT Serif', serif;
    color:#2f2b25;
    font-size:18px;

    transition:
        border-color 0.25s ease,
        box-shadow 0.25s ease,
        background-color 0.25s ease;
}

.gg-contact-form input:focus,
.gg-contact-form textarea:focus{
    outline:none;
    border-color:rgba(185,150,95,0.95);
    background:rgba(241,223,196,0.32);
    box-shadow:
        0 0 0 1px rgba(185,150,95,0.22),
        0 4px 16px rgba(85,60,35,0.08);
}

.gg-contact-form textarea{
    min-height:170px;
    resize:vertical;
}

.gg-checkbox{
    display:flex;
    gap:12px;
    align-items:center;
    margin-bottom:25px;
}

.gg-checkbox input{
    width:auto;
    margin:0;
}

.gg-contact-form button{
    position:relative;
    display:inline-flex;
    align-items:center;
    justify-content:center;
    isolation:isolate;
    overflow:hidden;

    min-width:145px;
    padding:11px 40px;

    background-color:rgba(31,31,31,0.92);
    background-image:
        linear-gradient(
            180deg,
            rgba(255,255,255,0.08) 0%,
            rgba(255,255,255,0.03) 42%,
            rgba(185,150,95,0.10) 100%
        );

    color:#B9965F;
    border:1px solid rgba(185,150,95,0.78);

    font-family:'PT Serif', serif;
    font-size:clamp(12px, 0.8vw, 15px);
    letter-spacing:0.25em;
    text-transform:uppercase;

    cursor:pointer;

    -webkit-backdrop-filter:blur(10px) saturate(130%);
    backdrop-filter:blur(10px) saturate(130%);

    box-shadow:
        inset 0 1px 0 rgba(255,255,255,0.12),
        inset 0 -1px 0 rgba(185,150,95,0.12),
        0 10px 24px rgba(0,0,0,0.16);

    transition:
        transform 0.25s ease,
        color 0.25s ease,
        border-color 0.25s ease,
        background-color 0.25s ease,
        box-shadow 0.25s ease;
}

.gg-contact-form button::before{
    content:"";
    position:absolute;
    inset:0;
    z-index:-1;
    pointer-events:none;

    background:
        radial-gradient(circle at 24% 18%, rgba(255,255,255,0.12), transparent 32%),
        radial-gradient(circle at 82% 78%, rgba(185,150,95,0.24), transparent 38%);
}

.gg-contact-form button::after{
    content:"";
    position:absolute;
    left:8%;
    top:0;
    width:84%;
    height:1px;
    pointer-events:none;

    background:linear-gradient(
        90deg,
        transparent,
        rgba(255,255,255,0.32),
        transparent
    );
}

.gg-contact-form button:hover{
    transform:translateY(-1px);
    color:#f1dfc4;
    border-color:rgba(185,150,95,0.96);
    background-color:rgba(47,43,37,0.96);

    box-shadow:
        inset 0 1px 0 rgba(255,255,255,0.16),
        inset 0 -1px 0 rgba(185,150,95,0.16),
        0 14px 30px rgba(0,0,0,0.20);
}

.gg-contact-form button:focus-visible{
    outline:2px solid rgba(185,150,95,0.55);
    outline-offset:3px;
}

.gg-contact-form button:active{
    transform:translateY(0);

    box-shadow:
        inset 0 1px 0 rgba(255,255,255,0.10),
        inset 0 -1px 0 rgba(185,150,95,0.14),
        0 7px 18px rgba(0,0,0,0.16);
}

.gg-contact-form button[disabled]{
    opacity:0.62;
    cursor:wait;
    transform:none;
}

.gg-contact-form button[disabled]:hover{
    color:#B9965F;
    border-color:rgba(185,150,95,0.78);
    background-color:rgba(31,31,31,0.92);

    box-shadow:
        inset 0 1px 0 rgba(255,255,255,0.12),
        inset 0 -1px 0 rgba(185,150,95,0.12),
        0 10px 24px rgba(0,0,0,0.16);
}

@supports not ((backdrop-filter:blur(2px)) or (-webkit-backdrop-filter:blur(2px))){
    .gg-contact-form button{
        background-color:#1f1f1f;
    }
}
.gg-form-note{
    max-width:620px;
    margin-top:25px;
}

.gg-form-note a{
    color:#9F8560;
    text-decoration:none;
    border-bottom:1px solid rgba(159,133,96,0.45);
}

.gg-form-note a:hover{
    border-bottom-color:#9F8560;
}

	.gg-contact-website{
    position:absolute;
    left:-9999px;
    width:1px;
    height:1px;
    opacity:0;
    pointer-events:none;
}

.gg-contact-message{
    max-width:620px;
    margin-top:18px !important;
    color:#9F8560 !important;
    font-family:'PT Serif', serif;
    font-size:clamp(14px,1vw,18px) !important;
    line-height:1.6 !important;
    letter-spacing:0.06em !important;
}

.gg-contact-message.is-error{
    color:#8f3d2f !important;
}


	
html{
    scroll-behavior:smooth;
}

@media(max-width:768px){
    .gg-contact-header{
        padding:46px 5% 42px;
    }

    .gg-contact-header h1{
        font-size:clamp(34px,10vw,48px);
        letter-spacing:0.1em;
    }

    .gg-contact-header p{
        font-size:14px;
        line-height:1.7;
        letter-spacing:0.04em;
    }

    .gg-info-page{
        padding:42px 5%;
    }

    .gg-info-heading{
        grid-template-columns:1fr;
        gap:12px;
        text-align:center;
        margin-bottom:32px;
    }

    .gg-info-subheading{
        margin-bottom:26px;
    }

    .gg-heading-image{
        max-width:260px;
        margin:0 auto;
    }

    .gg-info-heading .gg-small-title{
        font-size:clamp(18px,6vw,30px);
        letter-spacing:0.16em;
        white-space:normal;
    }

    .gg-info-block{
        scroll-margin-top:90px;
        margin-bottom:44px;
        padding-bottom:38px;
    }

    .gg-info-block h3{
        font-size:clamp(18px,5vw,24px);
        letter-spacing:0.03em;
    }

    .gg-info-block p{
        font-size:14px;
        line-height:1.7;
        letter-spacing:0.035em;
    }

    .gg-contact-page{
        width:100vw;
        max-width:100vw;
        margin-left:calc(50% - 50vw);
        margin-right:calc(50% - 50vw);
        grid-template-columns:1fr;
    }

    .gg-contact-left{
        padding:42px 7%;
    }

    .gg-contact-left h3{
        font-size:18px;
        letter-spacing:0.22em;
        margin-bottom:28px;
    }

    .gg-contact-left p{
        font-size:14px;
        line-height:1.65;
        letter-spacing:0.06em;
        margin-bottom:22px;
    }

    .gg-contact-ornament{
        margin:28px 0;
    }

    .gg-contact-ornament img{
        width:130px;
    }

    .gg-contact-info{
        grid-template-columns:42px 1fr;
        gap:14px;
        margin-top:24px;
    }

    .gg-contact-info span{
        font-size:11px;
        letter-spacing:0.16em;
    }

    .gg-contact-info strong{
        font-size:11px;
        letter-spacing:0.06em;
        line-height:1.45;
        word-break:break-word;
    }

    .gg-contact-right{
        padding:42px 7%;
    }

    .gg-form-title-row{
        gap:12px;
        margin-bottom:22px;
    }

    .gg-form-title-row span{
        font-size:18px;
        letter-spacing:0.22em;
    }

    .gg-form-title-row img{
        width:110px;
        max-width:38vw;
    }

    .gg-contact-right h2{
        font-size:clamp(30px,9vw,42px);
        letter-spacing:0.08em;
        line-height:1.2;
    }

    .gg-contact-right p,
    .gg-contact-form label{
        font-size:14px;
        letter-spacing:0.04em;
        line-height:1.6;
    }

    .gg-contact-form{
        max-width:100%;
    }

    .gg-contact-form input,
    .gg-contact-form textarea{
        font-size:16px;
        padding:12px;
        margin:7px 0 18px;
    }

    .gg-contact-form textarea{
        min-height:140px;
    }

    .gg-checkbox{
        align-items:flex-start;
        gap:10px;
    }

    .gg-contact-form button{
        width:100%;
        padding:12px 20px;
    }
}
</style>

	<script>
const ggContactAjaxUrl = <?php echo wp_json_encode(admin_url('admin-ajax.php')); ?>;

document.addEventListener('submit', function(e) {
    const form = e.target.closest('.gg-contact-form');
    if (!form) return;

    e.preventDefault();

    const nameInput = form.querySelector('input[name="name"]');
    const emailInput = form.querySelector('input[name="email"]');
    const messageInput = form.querySelector('textarea[name="message"]');
    const subjectInput = form.querySelector('input[name="subject"]');
    const websiteInput = form.querySelector('input[name="website"]');
    const nonceInput = form.querySelector('input[name="gg_contact_nonce"]');
    const feedback = form.querySelector('.gg-contact-message');
    const button = form.querySelector('button[type="submit"]');

    if (!nameInput || !nameInput.checkValidity()) {
        nameInput.reportValidity();
        return;
    }

    if (!emailInput || !emailInput.checkValidity()) {
        emailInput.reportValidity();
        return;
    }

    if (!messageInput || !messageInput.checkValidity()) {
        messageInput.reportValidity();
        return;
    }

    if (feedback) {
        feedback.textContent = '';
        feedback.classList.remove('is-error');
    }

    if (button) {
        button.disabled = true;
        button.textContent = 'SKICKAR…';
    }

    const formData = new FormData();
    formData.append('action', 'gg_contact_message');
    formData.append('name', nameInput.value);
    formData.append('email', emailInput.value);
    formData.append('message', messageInput.value);
    formData.append('subject', subjectInput ? subjectInput.value : '');
    formData.append('website', websiteInput ? websiteInput.value : '');
    formData.append('nonce', nonceInput ? nonceInput.value : '');

    fetch(ggContactAjaxUrl, {
        method: 'POST',
        body: formData,
        credentials: 'same-origin'
    })
    .then(function(response) {
        return response.json();
    })
    .then(function(data) {
        if (!data || !data.success) {
            throw new Error(data && data.data && data.data.message ? data.data.message : 'Något gick fel. Försök igen.');
        }

        if (feedback) {
            feedback.textContent = data.data && data.data.message ? data.data.message : 'Tack! Ditt meddelande har skickats.';
            feedback.classList.remove('is-error');
        }

        form.reset();
    })
    .catch(function(error) {
        if (feedback) {
            feedback.textContent = error.message;
            feedback.classList.add('is-error');
        }
    })
    .finally(function() {
        if (button) {
            button.disabled = false;
            button.textContent = 'SKICKA';
        }
    });
});
</script>
	
    <?php
    return ob_get_clean();
});

/**
 * Gold Goblins Design
 */
add_shortcode('gg_design', function() {
    ob_start();

    $gg_design_nonce = wp_create_nonce('gg_design_nonce');
    $gg_ajax_url = admin_url('admin-ajax.php');

    $gg_status = '';

    if ($_SERVER['REQUEST_METHOD'] === 'POST' && isset($_POST['gg_design_frontend_submit'])) {
        $gg_status = gg_process_design_frontend_submission();
    }
    ?>

<section class="gg-design-studio" id="gg-design-studio">

    <div class="gg-design-heading">
        <img class="gg-design-heading-image" src="https://www.goldgoblins.se/wp-content/uploads/2026/06/9b12-49af-8218-3f9fa75d735a.webp" alt="">
        <h1>Designa eget smycke i silver eller guld</h1>
        <img class="gg-design-heading-image" src="https://www.goldgoblins.se/wp-content/uploads/2026/06/e018b.webp" alt="">
    </div>

    <div class="gg-design-intro">
        <p>
            Beskriv din idé, välj material och stil. Vi skapar ett designunderlag och en AI-genererad inspirationsbild som kan skickas vidare till vår verkstad.
        </p>

        <p class="gg-design-note">
            Designunderlaget är inte en bindande offert. Slutlig form, material, konstruktion och pris bedöms alltid av Gold Goblins innan tillverkning.
        </p>

        <?php if ($gg_status === 'sent') : ?>
            <div class="gg-design-result-message success">
                Tack! Din designförfrågan har skickats till Gold Goblins. Vi återkommer när vi har gått igenom idén.
            </div>
        <?php elseif ($gg_status) : ?>
            <div class="gg-design-result-message error">
                Förfrågan kunde inte skickas just nu. Kontrollera att alla obligatoriska fält är ifyllda och försök igen.
            </div>
        <?php endif; ?>
    </div>

    <div class="gg-design-layout">

        <form class="gg-design-form" id="gg-design-form" action="" method="post">

            <input type="hidden" name="gg_design_frontend_submit" value="1">
            <input type="hidden" name="nonce" value="<?php echo esc_attr($gg_design_nonce); ?>">
            <input type="hidden" name="gg_ai_image_url" id="gg-ai-image-url-input" value="">
            <input type="text" name="gg_design_company" value="" autocomplete="off" tabindex="-1" class="gg-design-hp" aria-hidden="true">
            <input type="hidden" name="gg_design_started" value="<?php echo esc_attr(time()); ?>">

            <div class="gg-form-section">
                <div class="gg-design-kicker">DESIGNIDÉ</div>
                <h2>Beskriv smycket</h2>

                <div class="gg-design-grid">
                    <label>
                        <span>Smyckestyp *</span>
                        <select name="gg_jewelry_type" required>
                            <option value="">Välj smycke</option>
                            <option value="Ring">Ring</option>
                            <option value="Halsband">Halsband</option>
                            <option value="Armband">Armband</option>
                            <option value="Hängsmycke">Hängsmycke</option>
                            <option value="Örhängen">Örhängen</option>
                            <option value="Annat smycke">Annat smycke</option>
                        </select>
                    </label>

                    <label>
                        <span>Material *</span>
                        <select name="gg_material" required>
                            <option value="">Välj material</option>
                            <option value="Silver">Silver</option>
                            <option value="Guld">Guld</option>
                            <option value="Återvunnet guld eller silver">Återvunnet guld eller silver</option>
                            <option value="Osäker">Osäker</option>
                        </select>
                    </label>

                    <label>
                        <span>Storlek / längd</span>
                        <input type="text" name="gg_size" placeholder="Ex. ringstorlek 17,5 eller halsband 42 cm">
                    </label>

                    <label>
                        <span>Budget</span>
                        <select name="gg_budget">
                            <option value="">Välj ungefärlig budget</option>
                            <option value="Under 2 000 kr">Under 2 000 kr</option>
                            <option value="2 000–5 000 kr">2 000–5 000 kr</option>
                            <option value="5 000–10 000 kr">5 000–10 000 kr</option>
                            <option value="10 000 kr eller mer">10 000 kr eller mer</option>
                            <option value="Osäker">Osäker</option>
                        </select>
                    </label>
                </div>

                <fieldset class="gg-design-style-group">
                    <legend>Stil och uttryck</legend>

                    <label class="gg-style-choice">
                        <input type="checkbox" name="gg_style[]" value="Minimalistisk">
                        <span>Minimalistisk</span>
                    </label>

                    <label class="gg-style-choice">
                        <input type="checkbox" name="gg_style[]" value="Klassisk">
                        <span>Klassisk</span>
                    </label>

                    <label class="gg-style-choice">
                        <input type="checkbox" name="gg_style[]" value="Organisk">
                        <span>Organisk</span>
                    </label>

                    <label class="gg-style-choice">
                        <input type="checkbox" name="gg_style[]" value="Gotisk">
                        <span>Gotisk</span>
                    </label>

                    <label class="gg-style-choice">
                        <input type="checkbox" name="gg_style[]" value="Hamrad yta">
                        <span>Hamrad yta</span>
                    </label>

                    <label class="gg-style-choice">
                        <input type="checkbox" name="gg_style[]" value="Polerad yta">
                        <span>Polerad yta</span>
                    </label>

                    <label class="gg-style-choice">
                        <input type="checkbox" name="gg_style[]" value="Sten">
                        <span>Sten</span>
                    </label>

                    <label class="gg-style-choice">
                        <input type="checkbox" name="gg_style[]" value="Gravyr">
                        <span>Gravyr</span>
                    </label>
                </fieldset>

                <label class="gg-design-full">
                    <span>Beskriv din idé *</span>
                    <textarea name="gg_idea" rows="5" required placeholder="Exempel: Jag vill ha en handgjord silverring med organisk form, mörk sten och en diskret gravyr på insidan."></textarea>
                </label>
            </div>

            <div class="gg-form-section gg-form-section-contact">
                <div class="gg-design-kicker">KONTAKTUPPGIFTER</div>
                <h2>Vem ska vi kontakta?</h2>

                <div class="gg-design-grid">
                    <label>
                        <span>Namn *</span>
                        <input type="text" name="gg_name" autocomplete="name" required>
                    </label>

                    <label>
                        <span>E-post *</span>
                        <input type="email" name="gg_email" autocomplete="email" required>
                    </label>

                    <label>
                        <span>Telefon</span>
                        <input type="tel" name="gg_phone" autocomplete="tel">
                    </label>

                    <label>
                        <span>Önskat nästa steg</span>
                        <select name="gg_next_step">
                            <option value="Jag vill få en offert">Jag vill få en offert</option>
                            <option value="Jag vill boka rådgivning">Jag vill boka rådgivning</option>
                            <option value="Jag vill först veta om idén är möjlig">Jag vill först veta om idén är möjlig</option>
                        </select>
                    </label>
                </div>

                <label class="gg-design-consent">
                    <input type="checkbox" name="gg_consent" value="1" required>
                    <span>
                        Jag godkänner att Gold Goblins kontaktar mig angående min designförfrågan.
                        Jag förstår att designunderlaget är en inspirationsbeskrivning och inte en bindande offert.
                    </span>
                </label>
            </div>

            <div class="gg-design-actions">
                <button type="button" class="gg-design-button" id="gg-design-generate">
                    SKAPA DESIGNUNDERLAG
                </button>

                <button type="submit" class="gg-design-button" id="gg-design-submit">
                    SKICKA TILL VERKSTADEN
                </button>
            </div>

            <div class="gg-design-status" id="gg-design-status" aria-live="polite"></div>

        </form>

        <aside class="gg-design-preview">
            <div class="gg-design-preview-inner">

                <div class="gg-design-kicker">AI-INSPIRATION</div>

                <div class="gg-design-ai-placeholder" id="gg-design-ai-result">
                    <div class="gg-design-ai-title">AI-INSPIRATION</div>
                    <p>
                        Fyll i formuläret och klicka på “Skapa designunderlag”. Då skapas en inspirationsbild baserad på din beskrivning.
                    </p>
                </div>

                <div class="gg-design-preview-divider"></div>

                <div class="gg-design-kicker">DESIGNUNDERLAG</div>
                <h2>Din idé</h2>

                <div class="gg-design-brief" id="gg-design-brief">
                    När designunderlaget är skapat visas sammanfattningen här.
                </div>

            </div>
        </aside>

    </div>

</section>

<style>
.gg-design-studio{
    width:100%;
    background-color:#f1dfc4;
    background-image:
        radial-gradient(circle at 20% 15%, rgba(255,255,255,0.10), transparent 30%),
        radial-gradient(circle at 80% 35%, rgba(120,90,55,0.03), transparent 35%),
        radial-gradient(circle at 45% 80%, rgba(255,255,255,0.06), transparent 30%),
        linear-gradient(135deg, rgba(255,255,255,0.03), rgba(120,90,55,0.02));
    background-size:cover;
    background-position:center;
    padding:clamp(28px,3vw,52px) 5% clamp(34px,3.5vw,58px);
    box-sizing:border-box;
}

.gg-design-hp{
    position:absolute !important;
    left:-9999px !important;
    width:1px !important;
    height:1px !important;
    opacity:0 !important;
    pointer-events:none !important;
}

.gg-design-heading{
    max-width:1050px;
    margin:0 auto clamp(18px,2.2vw,32px);
    display:grid;
    grid-template-columns:1fr auto 1fr;
    align-items:center;
    gap:clamp(18px,2.5vw,46px);
}

.gg-design-heading-image{
    width:100%;
    height:auto;
    display:block;
}

.gg-design-heading h1{
    margin:0;
    color:#B9965F;
    font-family:'PT Serif', serif;
    font-size:clamp(24px,2.5vw,42px);
    letter-spacing:0.18em;
    white-space:nowrap;
    font-weight:400;
    text-align:center;
}

.gg-design-intro{
    width:min(100%, 1080px);
    margin:0 auto clamp(22px,2.4vw,36px);
    display:grid;
    grid-template-columns:minmax(0, 1.08fr) minmax(280px, 0.92fr);
    gap:clamp(20px,3vw,44px);
    align-items:center;
    text-align:left;
}

.gg-design-intro p{
    margin:0;
    color:#2f2b25;
    font-family:'PT Serif', serif;
    font-size:clamp(15px,1.05vw,20px);
    line-height:1.6;
    letter-spacing:0.04em;
}

.gg-design-note{
    max-width:none;
    padding:clamp(12px,1.2vw,18px);
    border:1px solid rgba(170,138,88,0.32);
    background:rgba(241,223,196,0.24);
    font-size:clamp(13px,0.9vw,16px) !important;
    line-height:1.55 !important;
}

.gg-design-result-message{
    grid-column:1 / -1;
    margin:0;
    padding:clamp(13px,1.25vw,20px);
    border:1px solid rgba(170,138,88,0.5);
    color:#2f2b25;
    font-family:'PT Serif', serif;
    font-size:clamp(14px,1vw,17px);
    line-height:1.6;
    letter-spacing:0.03em;
}

.gg-design-result-message.success{
    border-color:rgba(63,111,63,0.55);
    color:#3f6f3f;
}

.gg-design-result-message.error{
    border-color:rgba(138,45,45,0.55);
    color:#8a2d2d;
}

.gg-design-layout{
    width:min(100%, 1180px);
    margin:0 auto;
    display:grid;
    grid-template-columns:minmax(0, 1fr) minmax(320px, 0.88fr);
    gap:clamp(22px,2.8vw,44px);
    align-items:start;
}

.gg-design-form,
.gg-design-preview-inner{
    border:1px solid rgba(170,138,88,0.36);
    background:rgba(241,223,196,0.36);
    box-sizing:border-box;
    padding:clamp(20px,2.1vw,32px);
}

.gg-form-section + .gg-form-section{
    margin-top:clamp(22px,2.4vw,34px);
    padding-top:clamp(20px,2.2vw,30px);
    border-top:1px solid rgba(170,138,88,0.28);
}

.gg-design-kicker{
    color:#B9965F;
    font-family:'PT Serif', serif;
    font-size:clamp(12px,0.78vw,14px);
    letter-spacing:0.24em;
    text-transform:uppercase;
    margin-bottom:clamp(7px,0.8vw,11px);
}

.gg-form-section h2,
.gg-design-preview h2{
    margin:0 0 clamp(16px,1.8vw,25px);
    color:#2f2b25;
    font-family:'PT Serif', serif;
    font-size:clamp(26px,2.25vw,38px);
    line-height:1.15;
    font-weight:400;
}

.gg-design-grid{
    display:grid;
    grid-template-columns:1fr 1fr;
    gap:clamp(14px,1.5vw,22px);
}

.gg-design-form label,
.gg-design-style-group{
    display:block;
}

.gg-design-form label span,
.gg-design-style-group legend{
    display:block;
    margin-bottom:6px;
    color:#B9965F;
    font-family:'PT Serif', serif;
    font-size:clamp(11px,0.78vw,14px);
    letter-spacing:0.14em;
    text-transform:uppercase;
    font-weight:400;
}

.gg-design-form input[type="text"],
.gg-design-form input[type="email"],
.gg-design-form input[type="tel"],
.gg-design-form select,
.gg-design-form textarea{
    width:100%;
    box-sizing:border-box;
    background:transparent;
    border:0;
    border-bottom:1px solid rgba(170,138,88,0.5);
    border-radius:0;
    color:#2f2b25;
    font-family:'PT Serif', serif;
    font-size:clamp(14px,0.95vw,16px);
    line-height:1.45;
    padding:8px 0;
    outline:none;
}

.gg-design-form textarea{
    min-height:112px;
    resize:vertical;
}

.gg-design-form select{
    cursor:pointer;
}

.gg-design-form input:focus,
.gg-design-form select:focus,
.gg-design-form textarea:focus{
    border-bottom-color:#B9965F;
}

.gg-design-full{
    margin-top:clamp(14px,1.5vw,22px);
}

.gg-design-style-group{
    border:0;
    padding:0;
    margin:clamp(18px,1.9vw,28px) 0 clamp(14px,1.5vw,22px);
    display:grid;
    grid-template-columns:repeat(4, minmax(0, 1fr));
    gap:9px;
}

.gg-design-style-group legend{
    grid-column:1 / -1;
}

.gg-style-choice{
    position:relative;
    display:block;
}

.gg-style-choice input{
    position:absolute;
    inset:0;
    opacity:0;
    cursor:pointer;
}

.gg-style-choice span{
    display:flex !important;
    align-items:center;
    justify-content:center;

    min-height:34px;
    margin:0 !important;
    padding:7px 10px;

    border:1px solid rgba(170,138,88,0.45);
    color:#6f5b3d !important;
    background:rgba(241,223,196,0.22);

    font-size:clamp(12px,0.8vw,14px) !important;
    line-height:1.25;
    letter-spacing:0.07em !important;
    text-transform:none !important;

    transition:
        background 0.2s ease,
        color 0.2s ease,
        border-color 0.2s ease,
        transform 0.2s ease;
}

.gg-style-choice input:checked + span{
    background:#B9965F;
    color:#f1dfc4 !important;
    border-color:#B9965F;
}

.gg-style-choice input:focus-visible + span,
.gg-style-choice:hover span{
    border-color:#B9965F;
    transform:translateY(-1px);
}

.gg-design-consent{
    position:relative;
    display:flex !important;
    gap:12px;
    align-items:flex-start;
    margin-top:clamp(18px,1.9vw,28px);
    color:#2f2b25;
    font-family:'PT Serif', serif;
    font-size:clamp(13px,0.9vw,15px);
    line-height:1.55;
}

.gg-design-consent input{
    flex:0 0 auto;
    width:18px;
    height:18px;
    margin-top:3px;
    accent-color:#B9965F;
}

.gg-design-consent span{
    color:#2f2b25 !important;
    text-transform:none !important;
    letter-spacing:0.03em !important;
    font-size:inherit !important;
    margin:0 !important;
}

.gg-design-actions{
    display:flex;
    flex-wrap:wrap;
    gap:12px;
    margin-top:clamp(22px,2.3vw,34px);
}

.gg-design-button{
    display:inline-flex;
    justify-content:center;
    align-items:center;
    padding:9px 17px;
    border:2px solid #aa8a58;
    color:#3a2c1f;
    text-decoration:none;
    font-family:Georgia, "Times New Roman", serif;
    font-size:clamp(12px,0.78vw,14px);
    text-transform:uppercase;
    letter-spacing:0.08em;
    cursor:pointer;
    background-color:#f1dfc4;
    background-image:
        radial-gradient(circle at 20% 15%, rgba(255,255,255,0.10), transparent 30%),
        radial-gradient(circle at 80% 35%, rgba(120,90,55,0.03), transparent 35%),
        radial-gradient(circle at 45% 80%, rgba(255,255,255,0.06), transparent 30%),
        linear-gradient(135deg, rgba(255,255,255,0.03), rgba(120,90,55,0.02));
    background-size:cover;
    background-position:center;
    transition:all 0.25s ease;
}

.gg-design-button:hover:not(:disabled){
    transform:translateY(-1px);
    border-color:#c4a26d;
    box-shadow:0 4px 12px rgba(0,0,0,0.08);
}

.gg-design-button:disabled{
    opacity:0.45;
    cursor:not-allowed;
}

#gg-design-submit{
    display:none;
}

.gg-design-status{
    margin-top:14px;
    color:#2f2b25;
    font-family:'PT Serif', serif;
    font-size:clamp(14px,0.95vw,16px);
    line-height:1.55;
}

.gg-design-status.success{
    color:#3f6f3f;
}

.gg-design-status.error{
    color:#8a2d2d;
}

.gg-design-preview{
    position:sticky;
    top:18px;
}

.gg-design-preview-inner{
    display:flex;
    flex-direction:column;
}

.gg-design-ai-placeholder{
    margin-top:clamp(12px,1.4vw,20px);
    padding:clamp(15px,1.6vw,24px);
    border:1px solid rgba(170,138,88,0.38);
    background:rgba(241,223,196,0.24);
}

.gg-design-ai-title{
    color:#B9965F;
    font-family:'PT Serif', serif;
    font-size:clamp(12px,0.78vw,14px);
    letter-spacing:0.2em;
    text-transform:uppercase;
    margin-bottom:8px;
}

.gg-design-ai-placeholder p{
    margin:0;
    color:#2f2b25;
    font-family:'PT Serif', serif;
    font-size:clamp(14px,0.95vw,16px);
    line-height:1.55;
}

.gg-design-ai-image{
    width:100%;
    max-height:clamp(220px,20vw,320px);
    height:auto;
    object-fit:contain;
    display:block;
    margin-top:clamp(12px,1.3vw,18px);
    border:1px solid rgba(170,138,88,0.38);
    background:#f1dfc4;
}

.gg-design-loading{
    opacity:0.72;
}

.gg-design-ai-disclaimer{
    margin:clamp(10px,1.2vw,16px) 0 0;
    color:#6f5b3d;
    font-family:'PT Serif', serif;
    font-size:clamp(12px,0.8vw,14px);
    line-height:1.5;
    font-style:italic;
}

.gg-design-preview-divider{
    width:100%;
    height:1px;
    background:rgba(170,138,88,0.3);
    margin:clamp(18px,2vw,26px) 0;
}

.gg-design-brief{
    min-height:clamp(110px,11vw,150px);
    white-space:pre-line;
    color:#2f2b25;
    font-family:'PT Serif', serif;
    font-size:clamp(14px,0.95vw,16px);
    line-height:1.65;
    letter-spacing:0.03em;
    border-top:1px solid rgba(170,138,88,0.3);
    border-bottom:1px solid rgba(170,138,88,0.3);
    padding:clamp(14px,1.6vw,22px) 0;
}

@media(max-width:1000px){
    .gg-design-style-group{
        grid-template-columns:repeat(2, minmax(0, 1fr));
    }
}

@media(max-width:900px){
    .gg-design-studio{
        padding:42px 5%;
    }

    .gg-design-heading{
        grid-template-columns:1fr;
        text-align:center;
        margin-bottom:30px;
    }

    .gg-design-heading-image{
        max-width:260px;
        margin:0 auto;
    }

    .gg-design-heading h1{
        white-space:normal;
        letter-spacing:0.12em;
    }

    .gg-design-intro{
        display:block;
        text-align:center;
        margin-bottom:34px;
    }

    .gg-design-intro p{
        margin:0 auto 18px;
    }

    .gg-design-layout{
        grid-template-columns:1fr;
    }

    .gg-design-preview{
        position:relative;
        top:auto;
    }

    .gg-design-grid{
        grid-template-columns:1fr;
    }

    .gg-design-form textarea{
        min-height:140px;
    }
}

@media(max-width:520px){
    .gg-design-studio{
        padding-left:4%;
        padding-right:4%;
    }

    .gg-design-style-group{
        grid-template-columns:1fr;
    }

    .gg-design-actions{
        flex-direction:column;
    }

    .gg-design-button{
        width:100%;
    }
}
</style>

<script>
document.addEventListener('DOMContentLoaded', function() {
    const form = document.getElementById('gg-design-form');
    if (!form) return;

    const ajaxUrl = <?php echo wp_json_encode($gg_ajax_url); ?>;

    const generateButton = document.getElementById('gg-design-generate');
    const submitButton = document.getElementById('gg-design-submit');

    const status = document.getElementById('gg-design-status');
    const briefBox = document.getElementById('gg-design-brief');
    const aiImageInput = document.getElementById('gg-ai-image-url-input');
    const aiResult = document.getElementById('gg-design-ai-result');

    let briefWasGenerated = false;

    function setStatus(message, type) {
        if (!status) return;

        status.textContent = message || '';
        status.classList.remove('success', 'error');

        if (type) {
            status.classList.add(type);
        }
    }

    function showSubmitButton() {
        if (submitButton) {
            submitButton.style.display = 'inline-flex';
        }
    }

    function hideSubmitButton() {
        if (submitButton) {
            submitButton.style.display = 'none';
        }
    }

    function resetGeneratedState() {
        briefWasGenerated = false;
        hideSubmitButton();

        if (aiImageInput) {
            aiImageInput.value = '';
        }

        setStatus('Designen har ändrats. Skapa designunderlaget igen innan du skickar till verkstaden.', 'error');
    }

    async function readJsonResponse(response) {
        const text = await response.text();

        try {
            return JSON.parse(text);
        } catch (error) {
            console.error('Gold Goblins AJAX svarade inte med JSON:', {
                status: response.status,
                response: text
            });

            throw new Error('Servern svarade inte korrekt när AI-bilden skulle skapas.');
        }
    }

    function getFieldValue(name) {
        const field = form.querySelector('[name="' + name + '"]');
        return field && field.value ? field.value.trim() : '';
    }

    function getSelectedStyles() {
        return Array.from(form.querySelectorAll('input[name="gg_style[]"]:checked')).map(function(input) {
            return input.value;
        });
    }

    function validateRequiredFields() {
        const requiredFields = Array.from(form.querySelectorAll('[required]'));

        for (const field of requiredFields) {
            if (field.type === 'checkbox' && !field.checked) {
                field.focus();
                setStatus('Fyll i alla obligatoriska fält innan designunderlaget skapas.', 'error');
                return false;
            }

            if (field.type !== 'checkbox' && !field.value.trim()) {
                field.focus();
                setStatus('Fyll i alla obligatoriska fält innan designunderlaget skapas.', 'error');
                return false;
            }
        }

        return true;
    }

    function buildBrief() {
        const jewelryType = getFieldValue('gg_jewelry_type') || 'Ej angivet';
        const material = getFieldValue('gg_material') || 'Ej angivet';
        const size = getFieldValue('gg_size') || 'Ej angivet';
        const budget = getFieldValue('gg_budget') || 'Ej angivet';
        const idea = getFieldValue('gg_idea') || 'Ej angivet';
        const nextStep = getFieldValue('gg_next_step') || 'Ej angivet';
        const styles = getSelectedStyles();
        const styleText = styles.length ? styles.join(', ') : 'Ej angivet';

        const brief =
            'Kundens designidé\n' +
            '-------------------------\n' +
            'Smyckestyp: ' + jewelryType + '\n' +
            'Material: ' + material + '\n' +
            'Stil: ' + styleText + '\n' +
            'Storlek / längd: ' + size + '\n' +
            'Budget: ' + budget + '\n' +
            'Önskat nästa steg: ' + nextStep + '\n\n' +
            'Beskrivning:\n' + idea + '\n\n' +
            'Verkstadsnotering:\n' +
            'Bedöm form, materialåtgång, hållbar konstruktion, eventuell steninfattning, gravyr och om designen bör justeras innan offert.';

        if (briefBox) {
            briefBox.textContent = brief;
        }

        briefWasGenerated = true;

        return brief;
    }

    function buildAiParams() {
        const nonceField = form.querySelector('[name="nonce"]');
        const params = new URLSearchParams();

        params.set('action', 'gg_generate_design_image');
        params.set('nonce', nonceField ? nonceField.value : '');
        params.set('gg_jewelry_type', getFieldValue('gg_jewelry_type'));
        params.set('gg_material', getFieldValue('gg_material'));
        params.set('gg_size', getFieldValue('gg_size'));
        params.set('gg_budget', getFieldValue('gg_budget'));
        params.set('gg_idea', getFieldValue('gg_idea'));

        getSelectedStyles().forEach(function(style) {
            params.append('gg_style[]', style);
        });

        return params;
    }

    async function generateDesignWithAi() {
        if (!validateRequiredFields()) return false;

        buildBrief();

        generateButton.disabled = true;
        generateButton.textContent = 'SKAPAR...';
        hideSubmitButton();

        if (aiResult) {
            aiResult.classList.add('gg-design-loading');
            aiResult.innerHTML =
                '<div class="gg-design-ai-title">AI-INSPIRATION</div>' +
                '<p>Skapar inspirationsbild. Detta kan ta en liten stund...</p>';
        }

        setStatus('Skapar designunderlag och inspirationsbild...', '');

        try {
            const response = await fetch(ajaxUrl, {
                method: 'POST',
                body: buildAiParams(),
                credentials: 'same-origin',
                headers: {
                    'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8'
                }
            });

            const result = await readJsonResponse(response);

            if (!result || !result.success || !result.data || !result.data.image_url) {
                throw new Error(result && result.data && result.data.message ? result.data.message : 'AI-bilden kunde inte skapas.');
            }

            if (aiImageInput) {
                aiImageInput.value = result.data.image_url;
            }

            if (aiResult) {
                aiResult.classList.remove('gg-design-loading');
                aiResult.innerHTML =
                    '<div class="gg-design-ai-title">AI-INSPIRATION</div>' +
                    '<p>Detta är en inspirationsbild baserad på din beskrivning. Slutlig design, hållbarhet, materialval och pris bedöms alltid av Gold Goblins innan tillverkning.</p>' +
                    '<img class="gg-design-ai-image" src="' + result.data.image_url + '" alt="AI-genererad inspirationsbild för specialdesignat smycke">' +
                    '<p class="gg-design-ai-disclaimer">Bilden är ett visuellt inspirationsunderlag och inte ett färdigt produktfoto.</p>';
            }

            showSubmitButton();
            setStatus('Designunderlaget är skapat. Kontrollera bilden och sammanfattningen, skicka sedan till verkstaden.', 'success');

            return true;

        } catch (error) {
            briefWasGenerated = false;
            hideSubmitButton();

            if (aiResult) {
                aiResult.classList.remove('gg-design-loading');
                aiResult.innerHTML =
                    '<div class="gg-design-ai-title">AI-INSPIRATION</div>' +
                    '<p>Inspirationsbilden kunde inte skapas just nu. Försök igen om en liten stund.</p>';
            }

            setStatus(error.message || 'AI-bilden kunde inte skapas just nu.', 'error');

            return false;

        } finally {
            generateButton.disabled = false;
            generateButton.textContent = 'SKAPA DESIGNUNDERLAG';
        }
    }

    const fieldsThatRequireRegeneration = form.querySelectorAll(
        'select[name="gg_jewelry_type"], select[name="gg_material"], input[name="gg_size"], select[name="gg_budget"], textarea[name="gg_idea"], input[name="gg_style[]"], select[name="gg_next_step"]'
    );

    fieldsThatRequireRegeneration.forEach(function(field) {
        field.addEventListener('change', function() {
            if (briefWasGenerated) {
                resetGeneratedState();
            }
        });

        field.addEventListener('input', function() {
            if (briefWasGenerated) {
                resetGeneratedState();
            }
        });
    });

    if (generateButton) {
        generateButton.addEventListener('click', function() {
            generateDesignWithAi();
        });
    }

    form.addEventListener('submit', function(e) {
        if (!validateRequiredFields()) {
            e.preventDefault();
            return;
        }

        if (!briefWasGenerated || !aiImageInput || !aiImageInput.value) {
            e.preventDefault();
            setStatus('Skapa designunderlaget innan du skickar till verkstaden.', 'error');
            return;
        }

        submitButton.disabled = true;
        submitButton.textContent = 'SKICKAR...';
        setStatus('Skickar designförfrågan...', '');
    });

    hideSubmitButton();
});
</script>

    <?php
    return ob_get_clean();
});


function gg_process_design_frontend_submission() {
    if (empty($_POST['nonce']) || !wp_verify_nonce(sanitize_text_field(wp_unslash($_POST['nonce'])), 'gg_design_nonce')) {
        return 'nonce';
    }

    $is_admin_user = is_user_logged_in() && current_user_can('manage_options');
    $client_key = gg_design_get_client_key();

    if (!$is_admin_user) {
        if (!empty($_POST['gg_design_company'])) {
            return 'spam';
        }

        $started = isset($_POST['gg_design_started']) ? (int) $_POST['gg_design_started'] : 0;
        $elapsed = $started ? time() - $started : 0;

        if ($elapsed < 5) {
            return 'spam';
        }

        $rate_key = 'gg_design_submit_rate_' . $client_key;
        $rate_count = (int) get_transient($rate_key);

        if ($rate_count >= 10) {
            return 'rate';
        }

        set_transient($rate_key, $rate_count + 1, HOUR_IN_SECONDS);
    }

    $name  = isset($_POST['gg_name']) ? sanitize_text_field(wp_unslash($_POST['gg_name'])) : '';
    $email = isset($_POST['gg_email']) ? sanitize_email(wp_unslash($_POST['gg_email'])) : '';
    $phone = isset($_POST['gg_phone']) ? sanitize_text_field(wp_unslash($_POST['gg_phone'])) : '';

    $jewelry_type = isset($_POST['gg_jewelry_type']) ? sanitize_text_field(wp_unslash($_POST['gg_jewelry_type'])) : '';
    $material     = isset($_POST['gg_material']) ? sanitize_text_field(wp_unslash($_POST['gg_material'])) : '';
    $size         = isset($_POST['gg_size']) ? sanitize_text_field(wp_unslash($_POST['gg_size'])) : '';
    $budget       = isset($_POST['gg_budget']) ? sanitize_text_field(wp_unslash($_POST['gg_budget'])) : '';
    $idea         = isset($_POST['gg_idea']) ? sanitize_textarea_field(wp_unslash($_POST['gg_idea'])) : '';
    $next_step    = isset($_POST['gg_next_step']) ? sanitize_text_field(wp_unslash($_POST['gg_next_step'])) : '';
    $ai_image_url = isset($_POST['gg_ai_image_url']) ? esc_url_raw(wp_unslash($_POST['gg_ai_image_url'])) : '';

    if ($ai_image_url && !gg_design_is_own_ai_image_url($ai_image_url)) {
        $ai_image_url = '';
    }

    $styles = [];

    if (isset($_POST['gg_style']) && is_array($_POST['gg_style'])) {
        $raw_styles = wp_unslash($_POST['gg_style']);

        foreach ($raw_styles as $style) {
            $styles[] = sanitize_text_field($style);
        }
    }

    $style_text = !empty($styles) ? implode(', ', $styles) : 'Ej angivet';

    if (!$name || !$email || !$jewelry_type || !$material || !$idea) {
        return 'missing';
    }

    if (!is_email($email)) {
        return 'email';
    }

    if (!$is_admin_user) {
        $email_rate_key = 'gg_design_submit_email_' . gg_design_get_email_key($email);
        $email_rate_count = (int) get_transient($email_rate_key);

        if ($email_rate_count >= 5) {
            return 'rate';
        }

        set_transient($email_rate_key, $email_rate_count + 1, DAY_IN_SECONDS);
    }

    if (empty($_POST['gg_consent'])) {
        return 'consent';
    }

    $generated_brief = gg_design_build_brief([
        'jewelry_type' => $jewelry_type,
        'material'     => $material,
        'style_text'   => $style_text,
        'size'         => $size,
        'budget'       => $budget,
        'idea'         => $idea,
        'next_step'    => $next_step,
    ]);

    $design_request_id = 0;

    if (function_exists('gg_save_customer_design_request')) {
        try {
            $design_request_id = gg_save_customer_design_request([
                'name'            => $name,
                'email'           => $email,
                'phone'           => $phone,
                'jewelry_type'    => $jewelry_type,
                'material'        => $material,
                'style_text'      => $style_text,
                'size'            => $size,
                'budget'          => $budget,
                'idea'            => $idea,
                'next_step'       => $next_step,
                'generated_brief' => $generated_brief,
                'inspiration_url' => '',
                'ai_image_url'    => $ai_image_url,
                'ai_prompt'       => '',
            ]);
        } catch (Throwable $error) {
            error_log('Gold Goblins kunddesign kunde inte sparas: ' . $error->getMessage());
            $design_request_id = 0;
        }
    }

    $recipient = apply_filters('gg_design_recipient_email', get_option('admin_email'));
    $mail_sent = false;

    if ($recipient && is_email($recipient)) {
        $subject = 'Ny designförfrågan från Gold Goblins';

        $message = "Ny designförfrågan\n";
        $message .= "====================\n\n";

        $message .= "Kund\n";
        $message .= "Namn: {$name}\n";
        $message .= "E-post: {$email}\n";
        $message .= "Telefon: " . ($phone ? $phone : 'Ej angivet') . "\n\n";

        $message .= "Smycke\n";
        $message .= "Smyckestyp: {$jewelry_type}\n";
        $message .= "Material: {$material}\n";
        $message .= "Stil: {$style_text}\n";
        $message .= "Storlek / längd: " . ($size ? $size : 'Ej angivet') . "\n";
        $message .= "Budget: " . ($budget ? $budget : 'Ej angivet') . "\n";
        $message .= "Nästa steg: " . ($next_step ? $next_step : 'Ej angivet') . "\n\n";

        $message .= "Kundens beskrivning\n";
        $message .= "--------------------\n";
        $message .= $idea . "\n\n";

        $message .= "Designunderlag\n";
        $message .= "--------------------\n";
        $message .= $generated_brief . "\n\n";

        if ($ai_image_url) {
            $message .= "AI-genererad inspirationsbild\n";
            $message .= "--------------------\n";
            $message .= $ai_image_url . "\n\n";
        }

        if (!empty($design_request_id)) {
            $message .= "Adminlänk\n";
            $message .= "--------------------\n";
            $message .= admin_url('post.php?post=' . intval($design_request_id) . '&action=edit') . "\n\n";
        }

        $message .= "Obs: Detta är en inspirationsförfrågan. Slutlig form, konstruktion och pris behöver bedömas av verkstaden.\n";

        $headers = [
            'Content-Type: text/plain; charset=UTF-8',
            'Reply-To: ' . $email,
        ];

        try {
            $mail_sent = wp_mail($recipient, $subject, $message, $headers);
        } catch (Throwable $error) {
            error_log('Gold Goblins designmail kunde inte skickas: ' . $error->getMessage());
            $mail_sent = false;
        }
    }

    if (!$design_request_id && !$mail_sent) {
        return 'send';
    }

    return 'sent';
}


add_action('wp_ajax_gg_generate_design_image', 'gg_generate_design_image');
add_action('wp_ajax_nopriv_gg_generate_design_image', 'gg_generate_design_image');

function gg_generate_design_image() {
    if (!check_ajax_referer('gg_design_nonce', 'nonce', false)) {
        wp_send_json_error([
            'message' => 'Säkerhetskontrollen misslyckades. Ladda om sidan och försök igen.'
        ], 403);
    }

    if (!defined('GG_OPENAI_API_KEY') || !GG_OPENAI_API_KEY) {
        error_log('Gold Goblins AI image error: GG_OPENAI_API_KEY saknas.');

        wp_send_json_error([
            'message' => 'Inspirationsbilden kunde inte skapas just nu. Designunderlaget går ändå att skicka till verkstaden.'
        ], 500);
    }

    $is_admin_user = is_user_logged_in() && current_user_can('manage_options');

    if (!$is_admin_user) {
        $gg_design_ai_limit = (int) get_option('gg_design_ai_hourly_limit', 3);
        $gg_design_ai_limit = min(20, max(1, $gg_design_ai_limit));

        $client_key = gg_design_get_client_key();
        $rate_key = 'gg_design_ai_rate_' . $client_key;
        $rate_count = (int) get_transient($rate_key);

        if ($rate_count >= $gg_design_ai_limit) {
            wp_send_json_error([
                'message' => 'För många AI-genereringar har gjorts från samma anslutning. Du kan göra ' . $gg_design_ai_limit . ' st varje timma.'
            ], 429);
        }

        $lock_key = 'gg_design_ai_lock_' . $client_key;

        if (get_transient($lock_key)) {
            wp_send_json_error([
                'message' => 'En inspirationsbild skapas redan. Vänta en stund och försök igen.'
            ], 429);
        }

        set_transient($rate_key, $rate_count + 1, HOUR_IN_SECONDS);
        set_transient($lock_key, 1, 3 * MINUTE_IN_SECONDS);
    }

    $jewelry_type = isset($_POST['gg_jewelry_type']) ? sanitize_text_field(wp_unslash($_POST['gg_jewelry_type'])) : '';
    $material     = isset($_POST['gg_material']) ? sanitize_text_field(wp_unslash($_POST['gg_material'])) : '';
    $size         = isset($_POST['gg_size']) ? sanitize_text_field(wp_unslash($_POST['gg_size'])) : '';
    $budget       = isset($_POST['gg_budget']) ? sanitize_text_field(wp_unslash($_POST['gg_budget'])) : '';
    $idea         = isset($_POST['gg_idea']) ? sanitize_textarea_field(wp_unslash($_POST['gg_idea'])) : '';

    $styles = [];

    if (isset($_POST['gg_style']) && is_array($_POST['gg_style'])) {
        $raw_styles = wp_unslash($_POST['gg_style']);

        foreach ($raw_styles as $style) {
            $styles[] = sanitize_text_field($style);
        }
    }

    $style_text = !empty($styles) ? implode(', ', $styles) : 'Ej angivet';

    if (!$jewelry_type || !$material || !$idea) {
        wp_send_json_error([
            'message' => 'Fyll i smyckestyp, material och beskrivning innan bilden skapas.'
        ], 400);
    }

    $image_prompt = gg_build_design_image_prompt([
        'jewelry_type' => $jewelry_type,
        'material'     => $material,
        'style_text'   => $style_text,
        'size'         => $size,
        'budget'       => $budget,
        'idea'         => $idea,
    ]);

    $model = defined('GG_OPENAI_IMAGE_MODEL') && GG_OPENAI_IMAGE_MODEL
        ? GG_OPENAI_IMAGE_MODEL
        : 'gpt-image-2';

    $payload = [
        'model'         => $model,
        'prompt'        => $image_prompt,
        'n'             => 1,
        'size'          => '1024x1024',
        'quality'       => 'low',
        'output_format' => 'webp',
    ];

    $response = wp_remote_post('https://api.openai.com/v1/images/generations', [
        'timeout' => 120,
        'headers' => [
            'Authorization' => 'Bearer ' . GG_OPENAI_API_KEY,
            'Content-Type'  => 'application/json',
        ],
        'body' => wp_json_encode($payload),
    ]);

    if (is_wp_error($response)) {
        if (isset($lock_key)) {
            delete_transient($lock_key);
        }

        wp_send_json_error([
            'message' => 'Kunde inte kontakta bildtjänsten. Försök igen senare.'
        ], 500);
    }

    $status_code = (int) wp_remote_retrieve_response_code($response);
    $body        = wp_remote_retrieve_body($response);
    $data        = json_decode($body, true);

    if ($status_code < 200 || $status_code >= 300) {
        if (!empty($data['error']['message'])) {
            error_log('Gold Goblins AI image error: ' . sanitize_text_field($data['error']['message']));
        }

        if (isset($lock_key)) {
            delete_transient($lock_key);
        }

        wp_send_json_error([
            'message' => 'Inspirationsbilden kunde inte skapas just nu. Designunderlaget går ändå att skicka till verkstaden.'
        ], 500);
    }

    if (empty($data['data'][0]['b64_json'])) {
        if (isset($lock_key)) {
            delete_transient($lock_key);
        }

        wp_send_json_error([
            'message' => 'Bildsvaret saknade bilddata.'
        ], 500);
    }

    $image_url = gg_save_design_ai_image($data['data'][0]['b64_json']);

    if (!$image_url) {
        if (isset($lock_key)) {
            delete_transient($lock_key);
        }

        wp_send_json_error([
            'message' => 'AI-bilden skapades men kunde inte sparas i WordPress.'
        ], 500);
    }

    if (isset($lock_key)) {
        delete_transient($lock_key);
    }

    wp_send_json_success([
        'image_url' => $image_url,
    ]);
}


function gg_design_build_brief($data) {
    $jewelry_type = $data['jewelry_type'] ?? '';
    $material     = $data['material'] ?? '';
    $style_text   = $data['style_text'] ?? '';
    $size         = $data['size'] ?? '';
    $budget       = $data['budget'] ?? '';
    $idea         = $data['idea'] ?? '';
    $next_step    = $data['next_step'] ?? '';

    $brief  = "Kundens designidé\n";
    $brief .= "-------------------------\n";
    $brief .= "Smyckestyp: " . ($jewelry_type ? $jewelry_type : 'Ej angivet') . "\n";
    $brief .= "Material: " . ($material ? $material : 'Ej angivet') . "\n";
    $brief .= "Stil: " . ($style_text ? $style_text : 'Ej angivet') . "\n";
    $brief .= "Storlek / längd: " . ($size ? $size : 'Ej angivet') . "\n";
    $brief .= "Budget: " . ($budget ? $budget : 'Ej angivet') . "\n";
    $brief .= "Önskat nästa steg: " . ($next_step ? $next_step : 'Ej angivet') . "\n\n";
    $brief .= "Beskrivning:\n";
    $brief .= ($idea ? $idea : 'Ej angivet') . "\n\n";
    $brief .= "Verkstadsnotering:\n";
    $brief .= "Bedöm form, materialåtgång, hållbar konstruktion, eventuell steninfattning, gravyr och om designen bör justeras innan offert.";

    return $brief;
}


function gg_build_design_image_prompt($data) {
    $jewelry_type = $data['jewelry_type'] ?? '';
    $material     = $data['material'] ?? '';
    $style_text   = $data['style_text'] ?? '';
    $size         = $data['size'] ?? '';
    $budget       = $data['budget'] ?? '';
    $idea         = $data['idea'] ?? '';

    $prompt  = "Create a realistic jewelry concept image for Gold Goblins, a Swedish handmade jewelry workshop in Lidköping.\n\n";
    $prompt .= "Jewelry type: {$jewelry_type}\n";
    $prompt .= "Material: {$material}\n";
    $prompt .= "Style and expression: {$style_text}\n";

    if ($size) {
        $prompt .= "Size or length reference: {$size}\n";
    }

    if ($budget) {
        $prompt .= "Approximate customer budget: {$budget}\n";
    }

    $prompt .= "\nCustomer idea:\n{$idea}\n\n";
    $prompt .= "Visual direction:\n";
    $prompt .= "- handcrafted fine jewelry concept\n";
    $prompt .= "- realistic metal surface, believable construction, wearable design\n";
    $prompt .= "- inspired by Swedish craftsmanship, precious metals, and timeless handmade design\n";
    $prompt .= "- warm beige stone or marble background matching a premium jewelry workshop aesthetic\n";
    $prompt .= "- elegant product presentation, soft natural light, high detail\n";
    $prompt .= "- no text, no logo, no watermark, no packaging mockup, no hands, no people\n";
    $prompt .= "- the image must feel like inspiration for a custom-made piece, not a finished product photo\n\n";
    $prompt .= "Important: The final image is only an inspiration concept. It should not imply that the exact item already exists.";

    return $prompt;
}


function gg_save_design_ai_image($b64_json) {
    $binary = base64_decode($b64_json, true);

    if (!$binary) {
        return false;
    }

    if (strlen($binary) > 5 * MB_IN_BYTES) {
        return false;
    }

    if (substr($binary, 0, 4) !== 'RIFF' || substr($binary, 8, 4) !== 'WEBP') {
        return false;
    }

    $upload_dir = wp_upload_dir();

    if (!empty($upload_dir['error'])) {
        return false;
    }

    $folder_name = 'gg-design-ai';
    $folder_path = trailingslashit($upload_dir['basedir']) . $folder_name;
    $folder_url  = trailingslashit($upload_dir['baseurl']) . $folder_name;

    if (!wp_mkdir_p($folder_path)) {
        return false;
    }

    $filename  = 'gg-design-' . gmdate('Ymd-His') . '-' . wp_generate_password(8, false, false) . '.webp';
    $file_path = trailingslashit($folder_path) . $filename;

    $saved = file_put_contents($file_path, $binary);

    if (!$saved) {
        return false;
    }

    return esc_url_raw(trailingslashit($folder_url) . $filename);
}


function gg_design_get_client_key() {
    $ip = isset($_SERVER['REMOTE_ADDR'])
        ? sanitize_text_field(wp_unslash($_SERVER['REMOTE_ADDR']))
        : 'unknown';

    return hash_hmac('sha256', $ip, wp_salt('nonce'));
}


function gg_design_get_email_key($email) {
    return hash_hmac('sha256', strtolower(trim($email)), wp_salt('nonce'));
}


function gg_design_is_own_ai_image_url($url) {
    if (!$url) {
        return false;
    }

    $upload_dir = wp_upload_dir();

    if (empty($upload_dir['baseurl'])) {
        return false;
    }

    $allowed_base = trailingslashit($upload_dir['baseurl']) . 'gg-design-ai/';

    return strpos($url, $allowed_base) === 0 && preg_match('/\.webp($|\?)/i', $url);
}

/**
 * Gold Goblins Kunddesigner Hub
 */
add_action('init', 'gg_register_customer_design_post_type');

function gg_register_customer_design_post_type() {
    register_post_type('gg_customer_design', [
        'labels' => [
            'name'               => 'Kunddesigner',
            'singular_name'      => 'Kunddesign',
            'menu_name'          => 'Kunddesigner',
            'name_admin_bar'     => 'Kunddesign',
            'add_new'            => 'Lägg till',
            'add_new_item'       => 'Lägg till kunddesign',
            'edit_item'          => 'Visa kunddesign',
            'new_item'           => 'Ny kunddesign',
            'view_item'          => 'Visa kunddesign',
            'search_items'       => 'Sök kunddesigner',
            'not_found'          => 'Inga kunddesigner hittades',
            'not_found_in_trash' => 'Inga kunddesigner i papperskorgen',
        ],
        'public'              => false,
        'show_ui'             => true,
        'show_in_menu'        => true,
        'menu_position'       => 26,
        'menu_icon'           => 'dashicons-art',
        'capability_type'     => 'post',
        'supports'            => ['title'],
        'has_archive'         => false,
        'exclude_from_search' => true,
    ]);
}


function gg_save_customer_design_request($data) {
    $customer_name = $data['name'] ?? '';
    $jewelry_type  = $data['jewelry_type'] ?? '';
    $created_date  = current_time('Y-m-d H:i');

    $post_title = trim($customer_name . ' – ' . $jewelry_type . ' – ' . $created_date);

    if (!$post_title) {
        $post_title = 'Ny kunddesign – ' . $created_date;
    }

    $post_id = wp_insert_post([
        'post_type'   => 'gg_customer_design',
        'post_status' => 'publish',
        'post_title'  => sanitize_text_field($post_title),
    ]);

    if (is_wp_error($post_id) || !$post_id) {
        return 0;
    }

    $meta_fields = [
        '_gg_design_status'          => 'Ny',
        '_gg_design_customer_name'   => $data['name'] ?? '',
        '_gg_design_email'           => $data['email'] ?? '',
        '_gg_design_phone'           => $data['phone'] ?? '',
        '_gg_design_jewelry_type'    => $data['jewelry_type'] ?? '',
        '_gg_design_material'        => $data['material'] ?? '',
        '_gg_design_style'           => $data['style_text'] ?? '',
        '_gg_design_size'            => $data['size'] ?? '',
        '_gg_design_budget'          => $data['budget'] ?? '',
        '_gg_design_next_step'       => $data['next_step'] ?? '',
        '_gg_design_idea'            => $data['idea'] ?? '',
        '_gg_design_generated_brief' => $data['generated_brief'] ?? '',
        '_gg_design_inspiration_url' => $data['inspiration_url'] ?? '',
        '_gg_design_ai_image_url'    => $data['ai_image_url'] ?? '',
        '_gg_design_ai_prompt'       => $data['ai_prompt'] ?? '',
    ];

    foreach ($meta_fields as $key => $value) {
        update_post_meta($post_id, $key, $value);
    }

    return $post_id;
}

add_filter('manage_gg_customer_design_posts_columns', 'gg_customer_design_columns');

function gg_customer_design_columns($columns) {
    return [
        'cb'              => $columns['cb'],
        'title'           => 'Förfrågan',
        'gg_customer'     => 'Kund',
        'gg_design_type'  => 'Smycke',
        'gg_material'     => 'Material',
        'gg_budget'       => 'Budget',
        'gg_status'       => 'Status',
        'gg_ai_image'     => 'AI-bild',
        'date'            => 'Datum',
    ];
}


add_action('manage_gg_customer_design_posts_custom_column', 'gg_customer_design_column_content', 10, 2);

function gg_customer_design_column_content($column, $post_id) {
    if ($column === 'gg_customer') {
        $name  = get_post_meta($post_id, '_gg_design_customer_name', true);
        $email = get_post_meta($post_id, '_gg_design_email', true);

        echo esc_html($name);

        if ($email) {
            echo '<br><a href="mailto:' . esc_attr($email) . '">' . esc_html($email) . '</a>';
        }
    }

    if ($column === 'gg_design_type') {
        echo esc_html(get_post_meta($post_id, '_gg_design_jewelry_type', true));
    }

    if ($column === 'gg_material') {
        echo esc_html(get_post_meta($post_id, '_gg_design_material', true));
    }

    if ($column === 'gg_budget') {
        echo esc_html(get_post_meta($post_id, '_gg_design_budget', true));
    }

    if ($column === 'gg_status') {
        $status = get_post_meta($post_id, '_gg_design_status', true);

        if (!$status) {
            $status = 'Ny';
        }

        echo esc_html($status);
    }

    if ($column === 'gg_ai_image') {
        $ai_image_url = get_post_meta($post_id, '_gg_design_ai_image_url', true);

        if ($ai_image_url) {
            echo '<a href="' . esc_url($ai_image_url) . '" target="_blank" rel="noopener noreferrer">';
            echo '<img src="' . esc_url($ai_image_url) . '" alt="" style="width:54px;height:54px;object-fit:cover;border:1px solid #b9965f;">';
            echo '</a>';
        } else {
            echo '—';
        }
    }
}

add_action('add_meta_boxes', 'gg_customer_design_add_meta_boxes');

function gg_customer_design_add_meta_boxes() {
    add_meta_box(
        'gg_customer_design_details',
        'Kunddesign',
        'gg_customer_design_render_details_box',
        'gg_customer_design',
        'normal',
        'high'
    );

    add_meta_box(
        'gg_customer_design_status',
        'Designstatus',
        'gg_customer_design_render_status_box',
        'gg_customer_design',
        'side',
        'high'
    );
}


function gg_customer_design_render_status_box($post) {
    wp_nonce_field('gg_customer_design_save_status', 'gg_customer_design_status_nonce');

    $status = get_post_meta($post->ID, '_gg_design_status', true);

    if (!$status) {
        $status = 'Ny';
    }

    $statuses = [
        'Ny',
        'Kontaktad',
        'Offert skickad',
        'Pågående',
        'Avslutad',
    ];
    ?>

    <p>
        <label for="gg-design-status"><strong>Status</strong></label>
    </p>

    <select id="gg-design-status" name="gg_design_status" style="width:100%;">
        <?php foreach ($statuses as $status_option) : ?>
            <option value="<?php echo esc_attr($status_option); ?>" <?php selected($status, $status_option); ?>>
                <?php echo esc_html($status_option); ?>
            </option>
        <?php endforeach; ?>
    </select>

    <p style="color:#646970;">
        Använd status för att följa upp kundens designförfrågan.
    </p>

    <?php
}


function gg_customer_design_render_details_box($post) {
    $fields = [
        'Kund'              => get_post_meta($post->ID, '_gg_design_customer_name', true),
        'E-post'            => get_post_meta($post->ID, '_gg_design_email', true),
        'Telefon'           => get_post_meta($post->ID, '_gg_design_phone', true),
        'Smyckestyp'        => get_post_meta($post->ID, '_gg_design_jewelry_type', true),
        'Material'          => get_post_meta($post->ID, '_gg_design_material', true),
        'Stil'              => get_post_meta($post->ID, '_gg_design_style', true),
        'Storlek / längd'   => get_post_meta($post->ID, '_gg_design_size', true),
        'Budget'            => get_post_meta($post->ID, '_gg_design_budget', true),
        'Önskat nästa steg' => get_post_meta($post->ID, '_gg_design_next_step', true),
    ];

    $idea            = get_post_meta($post->ID, '_gg_design_idea', true);
    $generated_brief = get_post_meta($post->ID, '_gg_design_generated_brief', true);
    $inspiration_url = get_post_meta($post->ID, '_gg_design_inspiration_url', true);
    $ai_image_url    = get_post_meta($post->ID, '_gg_design_ai_image_url', true);
    $ai_prompt       = get_post_meta($post->ID, '_gg_design_ai_prompt', true);
    ?>

    <style>
        .gg-admin-design-wrap{
            display:grid;
            grid-template-columns:minmax(0, 1fr) minmax(260px, 360px);
            gap:28px;
        }

        .gg-admin-design-card{
            border:1px solid #d7c4a5;
            background:#fffaf2;
            padding:18px;
            margin-bottom:18px;
        }

        .gg-admin-design-card h3{
            margin:0 0 14px;
            color:#8a6f45;
            font-family:Georgia, "Times New Roman", serif;
            letter-spacing:.08em;
            text-transform:uppercase;
            font-weight:400;
        }

        .gg-admin-design-table{
            width:100%;
            border-collapse:collapse;
        }

        .gg-admin-design-table th{
            width:170px;
            text-align:left;
            color:#8a6f45;
            padding:8px 10px 8px 0;
            vertical-align:top;
            font-weight:600;
        }

        .gg-admin-design-table td{
            padding:8px 0;
            vertical-align:top;
        }

        .gg-admin-design-pre{
            white-space:pre-wrap;
            line-height:1.6;
            margin:0;
            font-family:inherit;
        }

        .gg-admin-design-image{
            width:100%;
            height:auto;
            display:block;
            border:1px solid #d7c4a5;
            background:#f1dfc4;
        }

        .gg-admin-design-image-link{
            display:block;
            margin-top:8px;
        }

        @media(max-width:900px){
            .gg-admin-design-wrap{
                grid-template-columns:1fr;
            }
        }
    </style>

    <div class="gg-admin-design-wrap">

        <div>

            <div class="gg-admin-design-card">
                <h3>Kunduppgifter</h3>

                <table class="gg-admin-design-table">
                    <?php foreach ($fields as $label => $value) : ?>
                        <tr>
                            <th><?php echo esc_html($label); ?></th>
                            <td>
                                <?php
                                if ($label === 'E-post' && $value) {
                                    echo '<a href="mailto:' . esc_attr($value) . '">' . esc_html($value) . '</a>';
                                } else {
                                    echo $value ? esc_html($value) : '—';
                                }
                                ?>
                            </td>
                        </tr>
                    <?php endforeach; ?>
                </table>
            </div>

            <div class="gg-admin-design-card">
                <h3>Kundens idé</h3>
                <pre class="gg-admin-design-pre"><?php echo esc_html($idea ? $idea : 'Ingen idé angiven.'); ?></pre>
            </div>

            <div class="gg-admin-design-card">
                <h3>Designunderlag</h3>
                <pre class="gg-admin-design-pre"><?php echo esc_html($generated_brief ? $generated_brief : 'Inget designunderlag sparat.'); ?></pre>
            </div>

            <?php if ($ai_prompt) : ?>
                <div class="gg-admin-design-card">
                    <h3>AI-prompt</h3>
                    <pre class="gg-admin-design-pre"><?php echo esc_html($ai_prompt); ?></pre>
                </div>
            <?php endif; ?>

        </div>

        <div>

            <div class="gg-admin-design-card">
                <h3>AI-inspiration</h3>

                <?php if ($ai_image_url) : ?>
                    <img class="gg-admin-design-image" src="<?php echo esc_url($ai_image_url); ?>" alt="">
                    <a class="gg-admin-design-image-link" href="<?php echo esc_url($ai_image_url); ?>" target="_blank" rel="noopener noreferrer">
                        Öppna AI-bild
                    </a>
                <?php else : ?>
                    <p>Ingen AI-bild sparad.</p>
                <?php endif; ?>
            </div>

            <div class="gg-admin-design-card">
                <h3>Kundens inspirationsbild</h3>

                <?php if ($inspiration_url) : ?>
                    <img class="gg-admin-design-image" src="<?php echo esc_url($inspiration_url); ?>" alt="">
                    <a class="gg-admin-design-image-link" href="<?php echo esc_url($inspiration_url); ?>" target="_blank" rel="noopener noreferrer">
                        Öppna kundens bild
                    </a>
                <?php else : ?>
                    <p>Ingen inspirationsbild uppladdad.</p>
                <?php endif; ?>
            </div>

        </div>

    </div>

    <?php
}


add_action('save_post_gg_customer_design', 'gg_customer_design_save_status');

function gg_customer_design_save_status($post_id) {
    if (!isset($_POST['gg_customer_design_status_nonce'])) {
        return;
    }

    if (!wp_verify_nonce(sanitize_text_field(wp_unslash($_POST['gg_customer_design_status_nonce'])), 'gg_customer_design_save_status')) {
        return;
    }

    if (!current_user_can('edit_post', $post_id)) {
        return;
    }

    if (defined('DOING_AUTOSAVE') && DOING_AUTOSAVE) {
        return;
    }

    if (isset($_POST['gg_design_status'])) {
        update_post_meta($post_id, '_gg_design_status', sanitize_text_field(wp_unslash($_POST['gg_design_status'])));
    }
}

add_action('admin_menu', 'gg_customer_design_ai_settings_menu');

function gg_customer_design_ai_settings_menu() {
    add_submenu_page(
        'edit.php?post_type=gg_customer_design',
        'AI-inställningar',
        'AI-inställningar',
        'manage_options',
        'gg-customer-design-ai-settings',
        'gg_customer_design_ai_settings_page'
    );
}

function gg_customer_design_ai_settings_page() {
    if (!current_user_can('manage_options')) {
        wp_die('Du har inte behörighet att ändra dessa inställningar.');
    }

    $current_limit = (int) get_option('gg_design_ai_hourly_limit', 3);
    $current_limit = min(20, max(1, $current_limit));

    if (
        isset($_POST['gg_design_ai_limit_nonce']) &&
        wp_verify_nonce(
            sanitize_text_field(wp_unslash($_POST['gg_design_ai_limit_nonce'])),
            'gg_design_ai_save_limit'
        )
    ) {
        $action = isset($_POST['gg_design_ai_limit_action'])
            ? sanitize_text_field(wp_unslash($_POST['gg_design_ai_limit_action']))
            : '';

        $new_limit = $current_limit;

        if ($action === 'minus') {
            $new_limit = max(1, $current_limit - 1);
        }

        if ($action === 'plus') {
            $new_limit = min(20, $current_limit + 1);
        }

        if ($action === 'save') {
            $posted_limit = isset($_POST['gg_design_ai_hourly_limit'])
                ? (int) $_POST['gg_design_ai_hourly_limit']
                : 3;

            $new_limit = min(20, max(1, $posted_limit));
        }

        update_option('gg_design_ai_hourly_limit', $new_limit, false);
        $current_limit = $new_limit;

        echo '<div class="notice notice-success is-dismissible"><p>Sparat.</p></div>';
    }
    ?>

    <div class="wrap">
        <h1>AI-inställningar</h1>

        <form method="post">
            <?php wp_nonce_field('gg_design_ai_save_limit', 'gg_design_ai_limit_nonce'); ?>

            <table class="form-table" role="presentation">
                <tr>
                    <th scope="row">Bilder per timme</th>
                    <td>
                        <div style="display:flex;align-items:center;gap:10px;">
                            <button
                                type="submit"
                                class="button"
                                name="gg_design_ai_limit_action"
                                value="minus"
                            >−</button>

                            <input
                                type="number"
                                name="gg_design_ai_hourly_limit"
                                value="<?php echo esc_attr($current_limit); ?>"
                                min="1"
                                max="20"
                                style="width:80px;text-align:center;"
                            >

                            <button
                                type="submit"
                                class="button"
                                name="gg_design_ai_limit_action"
                                value="plus"
                            >+</button>

                            <button
                                type="submit"
                                class="button button-primary"
                                name="gg_design_ai_limit_action"
                                value="save"
                            >Spara</button>
                        </div>

                        <p class="description">Maxgräns: 20.</p>
                    </td>
                </tr>
            </table>
        </form>
    </div>

    <?php
}

/**
 * Gold Goblins Design Promo
 */
add_shortcode('gg_home_design', function() {
    ob_start();
    ?>

<section class="gg-home-design-promo">

    <div class="gg-home-design-promo-inner">

        <div class="gg-home-design-promo-text">
            <div class="gg-home-design-promo-kicker">SPECIALBESTÄLLNING</div>

            <h2>Designa eget smycke</h2>

            <p>
                Beskriv din idé, få ett inspirationsunderlag och skicka förfrågan direkt till vår verkstad.
            </p>
        </div>

        <div class="gg-home-design-promo-steps" aria-label="Designprocess">
            <span>Idé</span>
            <i></i>
            <span>Inspiration</span>
            <i></i>
            <span>Verkstad</span>
        </div>

        <a href="/design/" class="gg-home-design-promo-button">
            Designa ditt smycke
        </a>

    </div>

</section>

<style>
.gg-home-design-promo{
    position:relative;

    width:100%;
    background-color:#f1dfc4;
    background-image:
        radial-gradient(circle at 20% 15%, rgba(255,255,255,0.10), transparent 30%),
        radial-gradient(circle at 80% 35%, rgba(120,90,55,0.03), transparent 35%),
        radial-gradient(circle at 45% 80%, rgba(255,255,255,0.06), transparent 30%),
        linear-gradient(135deg, rgba(255,255,255,0.03), rgba(120,90,55,0.02));
    background-size:cover;
    background-position:center;

    border-top:0;
    border-bottom:0;

    box-sizing:border-box;
}

	.gg-home-design-promo::before{
    content:"";
    position:absolute;
    left:0;
    right:0;
    top:0;

    height:1px;

    background:linear-gradient(
        90deg,
        transparent 0%,
        rgba(159,133,96,0.28) 18%,
        rgba(159,133,96,0.70) 50%,
        rgba(159,133,96,0.28) 82%,
        transparent 100%
    );

    pointer-events:none;
    z-index:2;
}
	
.gg-home-design-promo-inner{
    width:min(86vw, 1160px);
    margin:0 auto;
    min-height:clamp(145px, 11vw, 195px);
    padding:clamp(24px, 2.4vw, 38px) 0;
    display:grid;
    grid-template-columns:minmax(280px, 0.9fr) minmax(260px, 0.65fr) auto;
    gap:clamp(28px, 4.5vw, 76px);
    align-items:center;
}

.gg-home-design-promo-kicker{
    color:#B9965F;
    font-family:'PT Serif', serif;
    font-size:clamp(11px, 0.75vw, 14px);
    letter-spacing:0.34em;
    text-transform:uppercase;
    margin-bottom:clamp(8px, 0.8vw, 12px);
}

.gg-home-design-promo-text h2{
    margin:0 0 clamp(8px, 0.8vw, 12px);
    color:#2f2b25;
    font-family:'PT Serif', serif;
    font-size:clamp(30px, 2.65vw, 48px);
    line-height:1.08;
    font-weight:400;
    letter-spacing:0.025em;
}

.gg-home-design-promo-text p{
    max-width:500px;
    margin:0;
    color:#2f2b25;
    font-family:'PT Serif', serif;
    font-size:clamp(14px, 0.95vw, 18px);
    line-height:1.62;
    letter-spacing:0.035em;
}

.gg-home-design-promo-steps{
    display:flex;
    align-items:center;
    justify-content:center;
    gap:clamp(9px, 0.9vw, 15px);
    white-space:nowrap;
}

.gg-home-design-promo-steps span{
    color:#2f2b25;
    font-family:'PT Serif', serif;
    font-size:clamp(11px, 0.78vw, 14px);
    letter-spacing:0.19em;
    text-transform:uppercase;
}

.gg-home-design-promo-steps i{
    width:clamp(24px, 2.3vw, 42px);
    height:1px;
    display:block;
    background:rgba(170,138,88,0.52);
}

.gg-home-design-promo-button{
    position:relative;
    display:inline-flex;
    justify-content:center;
    align-items:center;
    isolation:isolate;
    overflow:hidden;

    min-width:clamp(170px, 12vw, 220px);
    padding:10px 19px;

    border:1px solid rgba(170,138,88,0.78);
    color:#3a2c1f;
    text-decoration:none;

    font-family:Georgia, "Times New Roman", serif;
    font-size:clamp(11px, 0.76vw, 14px);
    text-transform:uppercase;
    letter-spacing:0.085em;
    white-space:nowrap;

    background-color:rgba(241,223,196,0.34);
    background-image:
        linear-gradient(
            180deg,
            rgba(255,255,255,0.44) 0%,
            rgba(255,255,255,0.18) 44%,
            rgba(185,150,95,0.12) 100%
        );

    -webkit-backdrop-filter:blur(10px) saturate(135%);
    backdrop-filter:blur(10px) saturate(135%);

    box-shadow:
        inset 0 1px 0 rgba(255,255,255,0.48),
        inset 0 -1px 0 rgba(120,90,55,0.12),
        0 10px 24px rgba(0,0,0,0.10);

    transition:
        transform 0.25s ease,
        border-color 0.25s ease,
        background-color 0.25s ease,
        box-shadow 0.25s ease,
        color 0.25s ease;
}

.gg-home-design-promo-button::before{
    content:"";
    position:absolute;
    inset:0;
    z-index:-1;
    pointer-events:none;

    background:
        radial-gradient(circle at 22% 18%, rgba(255,255,255,0.36), transparent 32%),
        radial-gradient(circle at 82% 78%, rgba(185,150,95,0.22), transparent 36%);
}

.gg-home-design-promo-button::after{
    content:"";
    position:absolute;
    left:8%;
    top:0;
    width:84%;
    height:1px;
    pointer-events:none;

    background:linear-gradient(
        90deg,
        transparent,
        rgba(255,255,255,0.74),
        transparent
    );
}

.gg-home-design-promo-button:hover{
    transform:translateY(-1px);
    border-color:rgba(196,162,109,0.96);
    background-color:rgba(241,223,196,0.46);

    box-shadow:
        inset 0 1px 0 rgba(255,255,255,0.58),
        inset 0 -1px 0 rgba(120,90,55,0.15),
        0 14px 30px rgba(0,0,0,0.14);
}

.gg-home-design-promo-button:focus-visible{
    outline:2px solid rgba(170,138,88,0.55);
    outline-offset:3px;
}

.gg-home-design-promo-button:active{
    transform:translateY(0);
    box-shadow:
        inset 0 1px 0 rgba(255,255,255,0.42),
        inset 0 -1px 0 rgba(120,90,55,0.14),
        0 7px 18px rgba(0,0,0,0.10);
}

@supports not ((backdrop-filter:blur(2px)) or (-webkit-backdrop-filter:blur(2px))){
    .gg-home-design-promo-button{
        background-color:rgba(241,223,196,0.86);
    }
}

@media(max-width:1050px){
    .gg-home-design-promo-inner{
        width:min(88vw, 760px);
        grid-template-columns:1fr;
        gap:clamp(18px, 3vw, 28px);
        text-align:center;
    }

    .gg-home-design-promo-text p{
        margin:0 auto;
    }

    .gg-home-design-promo-steps{
        justify-content:center;
    }

    .gg-home-design-promo-button{
        width:fit-content;
        margin:0 auto;
    }
}

@media(max-width:560px){
    .gg-home-design-promo-inner{
        width:min(90vw, 420px);
        min-height:auto;
        padding:34px 0;
    }

    .gg-home-design-promo-text h2{
        font-size:clamp(32px, 9vw, 42px);
    }

    .gg-home-design-promo-steps{
        flex-wrap:wrap;
        gap:9px;
    }

    .gg-home-design-promo-steps i{
        width:26px;
    }

    .gg-home-design-promo-button{
        width:100%;
        box-sizing:border-box;
    }
}
</style>

    <?php
    return ob_get_clean();
});

/**
 * Gold Goblins Blogg Core & Admin
 */
add_action('init', 'gg_blog_register_content');

function gg_blog_register_content() {

    register_post_type('gg_blog_post', [
        'labels' => [
            'name'                  => 'Blogg',
            'singular_name'         => 'Blogginlägg',
            'menu_name'             => 'Blogg',
            'name_admin_bar'        => 'Blogginlägg',
            'add_new'               => 'Lägg till',
            'add_new_item'          => 'Lägg till blogginlägg',
            'edit_item'             => 'Redigera blogginlägg',
            'new_item'              => 'Nytt blogginlägg',
            'view_item'             => 'Visa blogginlägg',
            'view_items'            => 'Visa blogginlägg',
            'search_items'          => 'Sök blogginlägg',
            'not_found'             => 'Inga blogginlägg hittades',
            'not_found_in_trash'    => 'Inga blogginlägg hittades i papperskorgen',
            'all_items'             => 'Alla blogginlägg',
            'archives'              => 'Bloggarkiv',
            'attributes'            => 'Bloggattribut',
            'insert_into_item'      => 'Infoga i blogginlägg',
            'uploaded_to_this_item' => 'Uppladdat till detta blogginlägg',
            'featured_image'        => 'Utvald bild',
            'set_featured_image'    => 'Ange utvald bild',
            'remove_featured_image' => 'Ta bort utvald bild',
            'use_featured_image'    => 'Använd som utvald bild',
        ],
        'public'              => true,
        'show_ui'             => true,
        'show_in_menu'        => true,
        'menu_icon'           => 'dashicons-edit-page',
        'menu_position'       => 24,
        'supports'            => ['title', 'comments', 'revisions'],
        'has_archive'         => false,
        'publicly_queryable'  => true,
        'exclude_from_search' => false,
        'show_in_rest'        => true,
        'rewrite'             => [
            'slug'       => 'blog',
            'with_front' => false,
        ],
    ]);

	
	
    register_taxonomy('gg_blog_topic', ['gg_blog_post'], [
        'labels' => [
            'name'                       => 'Bloggämnen',
            'singular_name'              => 'Bloggämne',
            'menu_name'                  => 'Bloggämnen',
            'all_items'                  => 'Alla ämnen',
            'edit_item'                  => 'Redigera ämne',
            'view_item'                  => 'Visa ämne',
            'update_item'                => 'Uppdatera ämne',
            'add_new_item'               => 'Lägg till ämne',
            'new_item_name'              => 'Nytt ämnesnamn',
            'parent_item'                => 'Överordnat ämne',
            'parent_item_colon'          => 'Överordnat ämne:',
            'search_items'               => 'Sök ämnen',
            'popular_items'              => 'Populära ämnen',
            'separate_items_with_commas' => 'Separera ämnen med kommatecken',
            'add_or_remove_items'        => 'Lägg till eller ta bort ämnen',
            'choose_from_most_used'      => 'Välj bland mest använda ämnen',
            'not_found'                  => 'Inga ämnen hittades',
        ],
        'hierarchical'      => true,
        'show_ui'           => true,
        'show_admin_column' => true,
        'show_in_rest'      => true,
        'rewrite'           => [
            'slug'       => 'blog-amne',
            'with_front' => false,
        ],
    ]);
}

add_filter('use_block_editor_for_post_type', 'gg_blog_disable_block_editor', 10, 2);

function gg_blog_disable_block_editor($use_block_editor, $post_type) {
    if ($post_type === 'gg_blog_post') {
        return false;
    }

    return $use_block_editor;
}

add_action('init', 'gg_blog_insert_default_topics', 20);

function gg_blog_insert_default_topics() {

    if (get_option('gg_blog_default_topics_created')) {
        return;
    }

    $topics = [
        'Guld',
        'Silver',
        'Smyckesvård',
        'Värdering',
        'Specialbeställningar',
        'Återbruk',
        'Verkstaden',
    ];

    foreach ($topics as $topic) {
        if (!term_exists($topic, 'gg_blog_topic')) {
            wp_insert_term($topic, 'gg_blog_topic');
        }
    }

    update_option('gg_blog_default_topics_created', 1);
}

add_action('add_meta_boxes', 'gg_blog_add_admin_meta_boxes');

function gg_blog_add_admin_meta_boxes() {

    add_meta_box(
        'gg_blog_settings',
        'Blogginställningar',
        'gg_blog_render_settings_meta_box',
        'gg_blog_post',
        'side',
        'default'
    );
}

function gg_blog_render_settings_meta_box($post) {

    wp_nonce_field('gg_blog_save_settings', 'gg_blog_settings_nonce');

    $is_featured = get_post_meta($post->ID, '_gg_blog_featured', true);
    $reading_time = get_post_meta($post->ID, '_gg_blog_reading_time', true);

    ?>
    <p>
        <label>
            <input type="checkbox" name="gg_blog_featured" value="1" <?php checked($is_featured, '1'); ?>>
            Visa som utvald artikel
        </label>
    </p>

    <p>
        <label for="gg_blog_reading_time">
            Läsningstid
        </label>
        <input
            type="text"
            id="gg_blog_reading_time"
            name="gg_blog_reading_time"
            value="<?php echo esc_attr($reading_time); ?>"
            placeholder="Exempel: 4 min"
            style="width:100%;"
        >
    </p>

    <p style="color:#646970;font-size:12px;line-height:1.5;">
        Dessa fält används av bloggens frontend-snippet senare. De påverkar inte innehållet i sig.
    </p>
    <?php
}

add_action('save_post_gg_blog_post', 'gg_blog_save_settings_meta_box');

function gg_blog_save_settings_meta_box($post_id) {

    if (
        !isset($_POST['gg_blog_settings_nonce']) ||
        !wp_verify_nonce(sanitize_text_field(wp_unslash($_POST['gg_blog_settings_nonce'])), 'gg_blog_save_settings')
    ) {
        return;
    }

    if (defined('DOING_AUTOSAVE') && DOING_AUTOSAVE) {
        return;
    }

    if (!current_user_can('edit_post', $post_id)) {
        return;
    }

    $is_featured = isset($_POST['gg_blog_featured']) ? '1' : '';
    update_post_meta($post_id, '_gg_blog_featured', $is_featured);

    $reading_time = isset($_POST['gg_blog_reading_time'])
        ? sanitize_text_field(wp_unslash($_POST['gg_blog_reading_time']))
        : '';

    update_post_meta($post_id, '_gg_blog_reading_time', $reading_time);
}

add_filter('manage_gg_blog_post_posts_columns', 'gg_blog_admin_columns');

function gg_blog_admin_columns($columns) {

    $new_columns = [];

    foreach ($columns as $key => $label) {
        $new_columns[$key] = $label;

        if ($key === 'title') {
            $new_columns['gg_blog_topic'] = 'Ämne';
            $new_columns['gg_blog_featured'] = 'Utvald';
            $new_columns['gg_blog_comments'] = 'Kommentarer';
        }
    }

    return $new_columns;
}

add_action('manage_gg_blog_post_posts_custom_column', 'gg_blog_admin_column_content', 10, 2);

function gg_blog_admin_column_content($column, $post_id) {

    if ($column === 'gg_blog_topic') {
        $terms = get_the_terms($post_id, 'gg_blog_topic');

        if (!is_wp_error($terms) && !empty($terms)) {
            $names = wp_list_pluck($terms, 'name');
            echo esc_html(implode(', ', $names));
        } else {
            echo '—';
        }
    }

    if ($column === 'gg_blog_featured') {
        $is_featured = get_post_meta($post_id, '_gg_blog_featured', true);
        echo $is_featured === '1' ? 'Ja' : '—';
    }

    if ($column === 'gg_blog_comments') {
        echo esc_html(get_comments_number($post_id));
    }
}

add_filter('manage_edit-gg_blog_post_sortable_columns', 'gg_blog_sortable_admin_columns');

function gg_blog_sortable_admin_columns($columns) {

    $columns['gg_blog_comments'] = 'comment_count';

    return $columns;
}

add_filter('post_updated_messages', 'gg_blog_updated_messages');

function gg_blog_updated_messages($messages) {

    $messages['gg_blog_post'] = [
        0  => '',
        1  => 'Blogginlägget har uppdaterats.',
        2  => 'Eget fält uppdaterat.',
        3  => 'Eget fält borttaget.',
        4  => 'Blogginlägget har uppdaterats.',
        5  => 'Blogginlägget har återställts.',
        6  => 'Blogginlägget har publicerats.',
        7  => 'Blogginlägget har sparats.',
        8  => 'Blogginlägget har skickats.',
        9  => 'Blogginlägget har schemalagts.',
        10 => 'Utkastet har uppdaterats.',
    ];

    return $messages;
}

add_action('add_meta_boxes', 'gg_blog_add_structured_meta_boxes');

function gg_blog_add_structured_meta_boxes() {

    add_meta_box(
        'gg_blog_content_box',
        'Blogginlägg',
        'gg_blog_render_content_meta_box',
        'gg_blog_post',
        'normal',
        'high'
    );

    add_meta_box(
        'gg_blog_media_box',
        'Media',
        'gg_blog_render_media_meta_box',
        'gg_blog_post',
        'side',
        'default'
    );

    add_meta_box(
        'gg_blog_seo_box',
        'SEO-underlag',
        'gg_blog_render_seo_meta_box',
        'gg_blog_post',
        'normal',
        'default'
    );
}

function gg_blog_render_content_meta_box($post) {

    wp_nonce_field('gg_blog_save_content', 'gg_blog_content_nonce');

    $intro      = get_post_meta($post->ID, '_gg_blog_intro', true);
    $body       = get_post_meta($post->ID, '_gg_blog_body', true);
    $conclusion = get_post_meta($post->ID, '_gg_blog_conclusion', true);
    $cta_text   = get_post_meta($post->ID, '_gg_blog_cta_text', true);
    $cta_url    = get_post_meta($post->ID, '_gg_blog_cta_url', true);

    if (!$intro && $post->post_excerpt) {
        $intro = $post->post_excerpt;
    }

    if (!$body && $post->post_content) {
        $body = $post->post_content;
    }

    ?>
    <style>
        .gg-blog-admin-wrap{
            display:grid;
            grid-template-columns:minmax(0, 1fr);
            gap:18px;
        }

        .gg-blog-admin-card{
            border:1px solid #d7c4a5;
            background:#fffaf2;
            padding:18px;
        }

        .gg-blog-admin-card h3{
            margin:0 0 14px;
            color:#8a6f45;
            font-family:Georgia, "Times New Roman", serif;
            letter-spacing:.08em;
            text-transform:uppercase;
            font-weight:400;
        }

        .gg-blog-admin-card label{
            display:block;
            margin:0 0 6px;
            color:#8a6f45;
            font-weight:600;
        }

        .gg-blog-admin-card input[type="text"],
        .gg-blog-admin-card input[type="url"],
        .gg-blog-admin-card textarea{
            width:100%;
        }

        .gg-blog-admin-card textarea{
            min-height:90px;
        }

        .gg-blog-admin-help{
            margin:8px 0 0;
            color:#646970;
            font-size:12px;
            line-height:1.5;
        }
    </style>

    <div class="gg-blog-admin-wrap">

        <div class="gg-blog-admin-card">
            <h3>Ingress</h3>

            <label for="gg_blog_intro">Kort inledning</label>
            <textarea id="gg_blog_intro" name="gg_blog_intro"><?php echo esc_textarea($intro); ?></textarea>

            <p class="gg-blog-admin-help">
                Visas överst i blogginlägget och används även som utdrag om inget annat anges.
            </p>
        </div>

        <div class="gg-blog-admin-card">
            <h3>Brödtext</h3>

            <?php
            wp_editor($body, 'gg_blog_body', [
                'textarea_name' => 'gg_blog_body',
                'textarea_rows' => 14,
                'media_buttons' => false,
                'teeny'         => false,
                'quicktags'     => true,
            ]);
            ?>

            <p class="gg-blog-admin-help">
                Här skriver du själva blogginlägget. Använd gärna H2-rubriker för tydlig struktur.
            </p>
        </div>

        <div class="gg-blog-admin-card">
            <h3>Avslutning</h3>

            <label for="gg_blog_conclusion">Avslutande text</label>
            <textarea id="gg_blog_conclusion" name="gg_blog_conclusion"><?php echo esc_textarea($conclusion); ?></textarea>
        </div>

        <div class="gg-blog-admin-card">
            <h3>Call to action</h3>

            <p>
                <label for="gg_blog_cta_text">Knapptext</label>
                <input
                    type="text"
                    id="gg_blog_cta_text"
                    name="gg_blog_cta_text"
                    value="<?php echo esc_attr($cta_text); ?>"
                    placeholder="Exempel: Boka värdering"
                >
            </p>

            <p>
                <label for="gg_blog_cta_url">Knapp-länk</label>
                <input
                    type="url"
                    id="gg_blog_cta_url"
                    name="gg_blog_cta_url"
                    value="<?php echo esc_url($cta_url); ?>"
                    placeholder="https://www.goldgoblins.se/vardering/"
                >
            </p>
        </div>

    </div>
    <?php
}

function gg_blog_render_media_meta_box($post) {

    $image_id  = get_post_thumbnail_id($post->ID);
    $image_url = $image_id ? wp_get_attachment_image_url($image_id, 'medium') : '';

    $image_alt   = get_post_meta($post->ID, '_gg_blog_image_alt', true);
    $youtube_url = get_post_meta($post->ID, '_gg_blog_youtube_url', true);
    $video_url   = get_post_meta($post->ID, '_gg_blog_video_url', true);

    ?>
    <div class="gg-blog-media-box">

        <p>
            <strong>Huvudbild</strong>
        </p>

        <div class="gg-blog-image-preview" style="margin-bottom:10px;">
            <?php if ($image_url) : ?>
                <img src="<?php echo esc_url($image_url); ?>" alt="" style="width:100%;height:auto;display:block;border:1px solid #d7c4a5;">
            <?php else : ?>
                <p style="color:#646970;">Ingen bild vald.</p>
            <?php endif; ?>
        </div>

        <input
            type="hidden"
            class="gg-blog-image-id"
            name="gg_blog_featured_image_id"
            value="<?php echo esc_attr($image_id); ?>"
        >

        <p>
            <button type="button" class="button gg-blog-select-image">Välj bild</button>
            <button type="button" class="button gg-blog-remove-image">Ta bort</button>
        </p>

        <p>
            <label for="gg_blog_image_alt"><strong>ALT-text</strong></label>
            <input
                type="text"
                id="gg_blog_image_alt"
                name="gg_blog_image_alt"
                value="<?php echo esc_attr($image_alt); ?>"
                style="width:100%;"
                placeholder="Beskriv bilden kort"
            >
        </p>

        <hr>

        <p>
            <label for="gg_blog_youtube_url"><strong>YouTube-länk</strong></label>
            <input
                type="url"
                id="gg_blog_youtube_url"
                name="gg_blog_youtube_url"
                value="<?php echo esc_url($youtube_url); ?>"
                style="width:100%;"
                placeholder="https://www.youtube.com/watch?v=..."
            >
        </p>

        <p>
            <label for="gg_blog_video_url"><strong>Video-URL</strong></label>
            <input
                type="url"
                id="gg_blog_video_url"
                name="gg_blog_video_url"
                value="<?php echo esc_url($video_url); ?>"
                style="width:100%;"
                placeholder="Direktlänk till video"
            >
        </p>

    </div>
    <?php
}

function gg_blog_render_seo_meta_box($post) {

    $seo_title       = get_post_meta($post->ID, '_gg_blog_seo_title', true);
    $meta_desc       = get_post_meta($post->ID, '_gg_blog_meta_description', true);
    $focus_topic     = get_post_meta($post->ID, '_gg_blog_focus_topic', true);
    $internal_links  = get_post_meta($post->ID, '_gg_blog_internal_links', true);

    ?>
    <div class="gg-blog-admin-wrap">

        <div class="gg-blog-admin-card">
            <h3>SEO</h3>

            <p>
                <label for="gg_blog_seo_title">SEO-titel</label>
                <input
                    type="text"
                    id="gg_blog_seo_title"
                    name="gg_blog_seo_title"
                    value="<?php echo esc_attr($seo_title); ?>"
                    placeholder="Exempel: Värdering av smycken i Lidköping"
                >
            </p>

            <p>
                <label for="gg_blog_meta_description">Meta description</label>
                <textarea
                    id="gg_blog_meta_description"
                    name="gg_blog_meta_description"
                    placeholder="Kort sammanfattning för sökresultatet."
                ><?php echo esc_textarea($meta_desc); ?></textarea>
            </p>

            <p>
                <label for="gg_blog_focus_topic">Fokusämne</label>
                <input
                    type="text"
                    id="gg_blog_focus_topic"
                    name="gg_blog_focus_topic"
                    value="<?php echo esc_attr($focus_topic); ?>"
                    placeholder="Exempel: smyckesvärdering"
                >
            </p>

            <p>
                <label for="gg_blog_internal_links">Internlänkar att använda</label>
                <textarea
                    id="gg_blog_internal_links"
                    name="gg_blog_internal_links"
                    placeholder="/vardering/&#10;/var-verksamhet/&#10;/kontakta-oss/"
                ><?php echo esc_textarea($internal_links); ?></textarea>
            </p>

            <p class="gg-blog-admin-help">
                Detta är ett arbetsunderlag. Frontend och eventuell SEO-snippet kan läsa dessa fält senare.
            </p>
        </div>

    </div>
    <?php
}

add_action('save_post_gg_blog_post', 'gg_blog_save_structured_fields');

function gg_blog_save_structured_fields($post_id) {

    if (
        !isset($_POST['gg_blog_content_nonce']) ||
        !wp_verify_nonce(sanitize_text_field(wp_unslash($_POST['gg_blog_content_nonce'])), 'gg_blog_save_content')
    ) {
        return;
    }

    if (defined('DOING_AUTOSAVE') && DOING_AUTOSAVE) {
        return;
    }

    if (!current_user_can('edit_post', $post_id)) {
        return;
    }

    $intro = isset($_POST['gg_blog_intro'])
        ? sanitize_textarea_field(wp_unslash($_POST['gg_blog_intro']))
        : '';

    $body = isset($_POST['gg_blog_body'])
        ? wp_kses_post(wp_unslash($_POST['gg_blog_body']))
        : '';

    $conclusion = isset($_POST['gg_blog_conclusion'])
        ? sanitize_textarea_field(wp_unslash($_POST['gg_blog_conclusion']))
        : '';

    $cta_text = isset($_POST['gg_blog_cta_text'])
        ? sanitize_text_field(wp_unslash($_POST['gg_blog_cta_text']))
        : '';

    $cta_url = isset($_POST['gg_blog_cta_url'])
        ? esc_url_raw(wp_unslash($_POST['gg_blog_cta_url']))
        : '';

    $image_id = isset($_POST['gg_blog_featured_image_id'])
        ? absint($_POST['gg_blog_featured_image_id'])
        : 0;

    $image_alt = isset($_POST['gg_blog_image_alt'])
        ? sanitize_text_field(wp_unslash($_POST['gg_blog_image_alt']))
        : '';

    $youtube_url = isset($_POST['gg_blog_youtube_url'])
        ? esc_url_raw(wp_unslash($_POST['gg_blog_youtube_url']))
        : '';

    $video_url = isset($_POST['gg_blog_video_url'])
        ? esc_url_raw(wp_unslash($_POST['gg_blog_video_url']))
        : '';

    $seo_title = isset($_POST['gg_blog_seo_title'])
        ? sanitize_text_field(wp_unslash($_POST['gg_blog_seo_title']))
        : '';

    $meta_description = isset($_POST['gg_blog_meta_description'])
        ? sanitize_textarea_field(wp_unslash($_POST['gg_blog_meta_description']))
        : '';

    $focus_topic = isset($_POST['gg_blog_focus_topic'])
        ? sanitize_text_field(wp_unslash($_POST['gg_blog_focus_topic']))
        : '';

    $internal_links = isset($_POST['gg_blog_internal_links'])
        ? sanitize_textarea_field(wp_unslash($_POST['gg_blog_internal_links']))
        : '';

    update_post_meta($post_id, '_gg_blog_intro', $intro);
    update_post_meta($post_id, '_gg_blog_body', $body);
    update_post_meta($post_id, '_gg_blog_conclusion', $conclusion);
    update_post_meta($post_id, '_gg_blog_cta_text', $cta_text);
    update_post_meta($post_id, '_gg_blog_cta_url', $cta_url);
    update_post_meta($post_id, '_gg_blog_image_alt', $image_alt);
    update_post_meta($post_id, '_gg_blog_youtube_url', $youtube_url);
    update_post_meta($post_id, '_gg_blog_video_url', $video_url);
    update_post_meta($post_id, '_gg_blog_seo_title', $seo_title);
    update_post_meta($post_id, '_gg_blog_meta_description', $meta_description);
    update_post_meta($post_id, '_gg_blog_focus_topic', $focus_topic);
    update_post_meta($post_id, '_gg_blog_internal_links', $internal_links);

    if ($image_id) {
        update_post_meta($post_id, '_thumbnail_id', $image_id);
    } else {
        delete_post_meta($post_id, '_thumbnail_id');
    }

    /*
     * Synka till WordPress standardfält.
     * Det gör att sök, SEO-plugins, RSS och fallback-visning fortfarande har innehåll.
     */
    $synced_content = trim($intro . "\n\n" . $body . "\n\n" . $conclusion);

    remove_action('save_post_gg_blog_post', 'gg_blog_save_structured_fields');

    wp_update_post([
        'ID'           => $post_id,
        'post_content' => $synced_content,
        'post_excerpt' => $intro,
    ]);

    add_action('save_post_gg_blog_post', 'gg_blog_save_structured_fields');
}

add_action('admin_enqueue_scripts', 'gg_blog_enqueue_admin_media');

function gg_blog_enqueue_admin_media($hook) {
    $screen = get_current_screen();

    if (!$screen || $screen->post_type !== 'gg_blog_post') {
        return;
    }

    wp_enqueue_media();
}

add_action('admin_footer', 'gg_blog_admin_media_script');

function gg_blog_admin_media_script() {
    $screen = get_current_screen();

    if (!$screen || $screen->post_type !== 'gg_blog_post') {
        return;
    }

    ?>
    <script>
    document.addEventListener('click', function(e) {
        const selectButton = e.target.closest('.gg-blog-select-image');
        const removeButton = e.target.closest('.gg-blog-remove-image');

        if (selectButton) {
            e.preventDefault();

            const box = selectButton.closest('.gg-blog-media-box');
            const input = box.querySelector('.gg-blog-image-id');
            const preview = box.querySelector('.gg-blog-image-preview');

            const frame = wp.media({
                title: 'Välj huvudbild',
                button: {
                    text: 'Använd bild'
                },
                multiple: false
            });

            frame.on('select', function() {
                const attachment = frame.state().get('selection').first().toJSON();
                const imageUrl = attachment.sizes && attachment.sizes.medium
                    ? attachment.sizes.medium.url
                    : attachment.url;

                input.value = attachment.id;

                preview.innerHTML =
                    '<img src="' + imageUrl + '" alt="" style="width:100%;height:auto;display:block;border:1px solid #d7c4a5;">';
            });

            frame.open();
        }

        if (removeButton) {
            e.preventDefault();

            const box = removeButton.closest('.gg-blog-media-box');
            const input = box.querySelector('.gg-blog-image-id');
            const preview = box.querySelector('.gg-blog-image-preview');

            input.value = '';
            preview.innerHTML = '<p style="color:#646970;">Ingen bild vald.</p>';
        }
    });
    </script>
    <?php
}

/**
 * Gold Goblins Blogg Shortcode
 */
add_shortcode('gg_blog', 'gg_blog_render_shortcode');

function gg_blog_render_shortcode($atts = []) {

    if (!post_type_exists('gg_blog_post') || !taxonomy_exists('gg_blog_topic')) {
        return '<section class="gg-blog-page"><p>Bloggen är inte aktiverad ännu.</p></section>';
    }

    $atts = shortcode_atts([
        'posts_per_page' => 6,
    ], $atts, 'gg_blog');

    $posts_per_page = max(1, absint($atts['posts_per_page']));

    $current_topic = isset($_GET['gg_blog_topic'])
        ? sanitize_title(wp_unslash($_GET['gg_blog_topic']))
        : '';

    $current_search = isset($_GET['gg_blog_search'])
        ? sanitize_text_field(wp_unslash($_GET['gg_blog_search']))
        : '';

    $query = new WP_Query(gg_blog_get_query_args(1, $posts_per_page, $current_topic, $current_search));

    $topics = get_terms([
        'taxonomy'   => 'gg_blog_topic',
        'hide_empty' => false,
    ]);

    $blog_url = get_permalink();

    ob_start();
    ?>

<section
    id="gg-blog-app"
    class="gg-blog-page gg-section-has-top-divider"
    data-ajax-url="<?php echo esc_url(admin_url('admin-ajax.php')); ?>"
    data-nonce="<?php echo esc_attr(wp_create_nonce('gg_blog_load_posts')); ?>"
    data-posts-per-page="<?php echo esc_attr($posts_per_page); ?>"
    data-page="1"
    data-max-pages="<?php echo esc_attr($query->max_num_pages); ?>"
>

    <div class="gg-blog-heading">
        <img
            class="gg-blog-heading-image"
            src="https://www.goldgoblins.se/wp-content/uploads/2026/06/9b12-49af-8218-3f9fa75d735a.webp"
            alt=""
            loading="eager"
            decoding="async"
        >

        <h1>BLOG GOBLIN</h1>

        <img
            class="gg-blog-heading-image"
            src="https://www.goldgoblins.se/wp-content/uploads/2026/06/e018b.webp"
            alt=""
            loading="eager"
            decoding="async"
        >
    </div>

    <div class="gg-blog-intro">
        <p>
            Artiklar från Gold Goblins verkstad om handgjorda smycken, ädelmetaller,
            värdering, återbruk, skötsel och svenskt hantverk.
        </p>
    </div>

    <div class="gg-blog-layout">

        <aside class="gg-blog-topics" aria-label="Bloggämnen">
            <div class="gg-blog-side-title">Ämnen</div>

            <a
                href="<?php echo esc_url(remove_query_arg(['gg_blog_topic', 'gg_blog_search'], $blog_url)); ?>"
                class="gg-blog-topic <?php echo $current_topic === '' ? 'active' : ''; ?>"
                data-topic=""
                aria-pressed="<?php echo $current_topic === '' ? 'true' : 'false'; ?>"
            >
                Alla ämnen
            </a>

            <?php if (!is_wp_error($topics) && !empty($topics)) : ?>
                <?php foreach ($topics as $topic) : ?>
                    <?php
                    $topic_url = add_query_arg([
                        'gg_blog_topic' => $topic->slug,
                    ], $blog_url);

                    if ($current_search !== '') {
                        $topic_url = add_query_arg('gg_blog_search', $current_search, $topic_url);
                    }

                    $is_active = $current_topic === $topic->slug;
                    ?>

                    <a
                        href="<?php echo esc_url($topic_url); ?>"
                        class="gg-blog-topic <?php echo $is_active ? 'active' : ''; ?>"
                        data-topic="<?php echo esc_attr($topic->slug); ?>"
                        aria-pressed="<?php echo $is_active ? 'true' : 'false'; ?>"
                    >
                        <?php echo esc_html($topic->name); ?>
                    </a>
                <?php endforeach; ?>
            <?php endif; ?>
        </aside>

        <main class="gg-blog-feed" aria-label="Blogginlägg">

            <div id="gg-blog-results" class="gg-blog-results" aria-live="polite">
                <?php
                if ($query->have_posts()) :
                    while ($query->have_posts()) :
                        $query->the_post();
                        gg_blog_render_card(get_the_ID());
                    endwhile;
                    wp_reset_postdata();
                else :
                    echo '<p class="gg-blog-empty">Inga artiklar hittades.</p>';
                endif;
                ?>
            </div>

            <button type="button" id="gg-blog-load-more" class="gg-blog-load-more">
                Ladda fler artiklar
            </button>

            <div id="gg-blog-sentinel" class="gg-blog-sentinel" aria-hidden="true"></div>

        </main>

        <aside class="gg-blog-info" aria-label="Fördjupning och sök">

            <form class="gg-blog-search-form" action="<?php echo esc_url($blog_url); ?>" method="get">
                <input
                    type="hidden"
                    id="gg-blog-search-topic"
                    name="gg_blog_topic"
                    value="<?php echo esc_attr($current_topic); ?>"
                >

                <label for="gg-blog-search">Sök bland artiklar</label>

                <div class="gg-blog-search-box">
                    <input
                        type="search"
                        id="gg-blog-search"
                        name="gg_blog_search"
                        value="<?php echo esc_attr($current_search); ?>"
                        placeholder="Sök efter ämne, smycke eller metall"
                        autocomplete="off"
                    >

                    <button type="submit" aria-label="Sök">
                        →
                    </button>
                </div>
            </form>

            <?php gg_blog_render_featured_widget(); ?>

            <div class="gg-blog-metal-widget" aria-label="Aktuella metallpriser">

                <div class="gg-blog-metal-widget-head">
                    <span>Metallpris</span>
                    <strong>Aktuellt guldpris och silverpris</strong>
                    <small>
                        Här visas dagens marknadspris för guld och silver. Priset används som riktvärde när Gold Goblins värderar smycken, guld & silver.
                    </small>
                </div>

                <a class="gg-blog-metal-row" href="/guld/">
                    <span>Guld</span>

                    <strong class="gg-blog-metal-price">
                        <span id="gg-blog-gold-sek-g" class="gg-blog-metal-price-number">Laddar...</span>
                        <span class="gg-blog-metal-price-unit">SEK / G</span>
                    </strong>

                    <small id="gg-blog-gold-change">Hämtar dagspris</small>
                </a>

                <a class="gg-blog-metal-row" href="/silver/">
                    <span>Silver</span>

                    <strong class="gg-blog-metal-price">
                        <span id="gg-blog-silver-sek-g" class="gg-blog-metal-price-number">Laddar...</span>
                        <span class="gg-blog-metal-price-unit">SEK / G</span>
                    </strong>

                    <small id="gg-blog-silver-change">Hämtar dagspris</small>
                </a>

            </div>

            <a class="gg-blog-cta-card" href="/vardering/">
                <span>Värdering</span>
                <strong>Vill du värdera ett smycke?</strong>
                <small>Vi analyserar metallhalt, skick, utförande, märkningar och marknadsvärde.</small>
            </a>

            <a class="gg-blog-cta-card" href="/kontakta-oss/">
                <span>Fråga verkstaden</span>
                <strong>Har du en egen fråga?</strong>
                <small>Kontakta oss om specialbeställningar, skötsel, material eller värdering.</small>
            </a>

        </aside>

    </div>
</section>

<style>
.gg-blog-page{
    width:100%;
    background-color:#f1dfc4;
    background-image:
        radial-gradient(circle at 20% 15%, rgba(255,255,255,0.10), transparent 30%),
        radial-gradient(circle at 80% 35%, rgba(120,90,55,0.03), transparent 35%),
        radial-gradient(circle at 45% 80%, rgba(255,255,255,0.06), transparent 30%),
        linear-gradient(135deg, rgba(255,255,255,0.03), rgba(120,90,55,0.02));
    background-size:cover;
    background-position:center;
    padding:clamp(50px,6vw,105px) 3%;
    box-sizing:border-box;
    
}

.gg-section-has-top-divider{
    position:relative;
    border-top:0 !important;
}



.gg-blog-heading{
    max-width:950px;
    margin:0 auto clamp(24px,3vw,44px);
    display:grid;
    grid-template-columns:1fr auto 1fr;
    align-items:center;
    gap:clamp(20px,3vw,60px);
}

.gg-blog-heading-image{
    width:100%;
    height:auto;
    display:block;
}

.gg-blog-heading h1{
    margin:0;
    color:#B9965F;
    font-family:'PT Serif', serif;
    font-size:clamp(20px,3vw,46px);
    letter-spacing:0.22em;
    font-weight:400;
    white-space:nowrap;
}

.gg-blog-intro{
    max-width:850px;
    margin:0 auto clamp(35px,4vw,70px);
    text-align:center;
}

.gg-blog-intro p{
    margin:0;
    color:#2f2b25;
    font-family:'PT Serif', serif;
    font-size:clamp(16px,1.2vw,22px);
    line-height:1.75;
    letter-spacing:0.05em;
}

.gg-blog-layout{
    width:min(94vw, 1500px);
    margin:0 auto;
    display:grid;
    grid-template-columns:minmax(170px, 0.7fr) minmax(0, 2fr) minmax(230px, 0.85fr);
    gap:clamp(18px,2.5vw,44px);
    align-items:start;
}

.gg-blog-topics,
.gg-blog-info{
    position:sticky;
    top:24px;
}

.gg-blog-side-title{
    display:block;
    margin:0 0 clamp(18px,1.8vw,30px);
    color:#B9965F;
    font-family:'PT Serif', serif;
    font-size:clamp(11px,0.78vw,14px);
    letter-spacing:clamp(1.5px,0.16vw,3px);
    text-transform:uppercase;
    font-weight:400;
}

.gg-blog-search-form label{
    display:block;
    margin:0 0 14px;
    color:#B9965F;
    font-family:'PT Serif', serif;
    font-size:clamp(13px,0.9vw,16px);
    letter-spacing:0.18em;
    text-transform:uppercase;
}

.gg-blog-topic{
    position:relative;
    display:block;
    width:fit-content;
    max-width:100%;
    margin:0 0 clamp(13px,1.35vw,24px);
    padding:0;
    border:0;
    background:transparent;
    color:#2b2b2b;
    font-family:'PT Serif', serif;
    font-size:clamp(12px,0.82vw,15px);
    letter-spacing:clamp(1px,0.15vw,3px);
    line-height:1.35;
    text-transform:uppercase;
    text-align:left;
    text-decoration:none;
    white-space:normal;
    cursor:pointer;
    transition:color 0.25s ease;
    z-index:1;
}

.gg-blog-topic::before{
    content:"";
    position:absolute;
    left:50%;
    top:50%;
    width:calc(100% + 14px);
    height:1.45em;
    transform:translate(-50%, -50%) scale(0.72);
    background:radial-gradient(
        ellipse at center,
        rgba(255,255,255,0.72) 0%,
        rgba(255,250,240,0.42) 42%,
        rgba(255,255,255,0) 100%
    );
    border-radius:999px;
    filter:blur(4px);
    opacity:0;
    transition:opacity 0.25s ease, transform 0.25s ease;
    pointer-events:none;
    z-index:-1;
}

.gg-blog-topic:hover,
.gg-blog-topic.active{
    color:#B9965F;
}

.gg-blog-topic:hover::before,
.gg-blog-topic.active::before{
    opacity:1;
    transform:translate(-50%, -50%) scale(1);
}

.gg-blog-results{
    display:grid;
    grid-template-columns:1fr;
    gap:clamp(22px,3vw,44px);
}

.gg-blog-card{
    border:1px solid rgba(159,133,96,0.65);
    background:rgba(255,250,242,0.25);
    transition:border-color 0.25s ease, transform 0.25s ease, box-shadow 0.25s ease;
}

.gg-blog-card:hover{
    border-color:#B9965F;
    transform:translateY(-2px);
    box-shadow:0 10px 24px rgba(80,55,30,0.08);
}

.gg-blog-card-header{
    padding:clamp(24px,2.8vw,48px) clamp(24px,3.4vw,58px) clamp(20px,2.2vw,36px);
}

.gg-blog-card-header .gg-blog-card-topic{
    display:block;
    margin-bottom:12px;
    color:#B9965F;
    font-family:'PT Serif', serif;
    font-size:12px;
    letter-spacing:0.18em;
    text-transform:uppercase;
}

.gg-blog-card-header h2{
    max-width:820px;
    margin:0 auto;
    color:#2f2b25;
    font-family:'PT Serif', serif;
    font-size:clamp(28px,3vw,52px);
    font-weight:400;
    line-height:1.18;
    text-align:center;
}

.gg-blog-card-image-wrap{
    width:min(680px, 78%);
    margin:clamp(12px,1.4vw,24px) auto 0;
    background:transparent;
    overflow:visible;
    border:0;
}

.gg-blog-card-image-wrap figure,
.gg-blog-card-image-wrap .wp-block-image{
    display:block;
    width:100%;
    margin:0;
}

.gg-blog-card-image,
.gg-blog-card-image-wrap img{
    display:block !important;
    width:100% !important;
    max-width:100% !important;
    height:auto !important;
    max-height:none !important;
    object-fit:contain !important;
    margin:0 auto !important;
    border:1px solid rgba(159,133,96,0.38);
    box-sizing:border-box;
}

.gg-blog-card-image-wrap + .gg-blog-card-content{
    padding-top:clamp(38px,4.4vw,78px);
}

.gg-blog-card.is-expanded .gg-blog-card-image-wrap + .gg-blog-card-content{
    padding-top:clamp(52px,5.5vw,96px);
}

.gg-blog-card-content{
    padding:clamp(24px,2.8vw,46px) clamp(24px,3.4vw,58px);
}

.gg-blog-card-excerpt{
    max-width:820px;
    margin:0 auto;
    text-align:left;
}

.gg-blog-read-more{
    display:flex;
    align-items:center;
    justify-content:center;
    width:fit-content;
    margin:clamp(22px,2.4vw,34px) auto 0;
    padding:0;
    border:0;
    border-bottom:1px solid rgba(185,150,95,0.45);
    background:transparent;
    color:#B9965F;
    font-family:'PT Serif', serif;
    font-size:13px;
    letter-spacing:0.18em;
    text-transform:uppercase;
    cursor:pointer;
}

.gg-blog-read-more:hover{
    color:#2f2b25;
    border-bottom-color:#2f2b25;
}

.gg-blog-read-more[disabled]{
    opacity:0.55;
    cursor:not-allowed;
}

.gg-blog-card-meta{
    display:flex;
    justify-content:center;
    flex-wrap:wrap;
    gap:14px clamp(22px,3vw,70px);
    margin-top:clamp(18px,2vw,30px);
    padding:clamp(14px,1.6vw,24px) 0 0;
    border-top:1px solid rgba(159,133,96,0.35);
    color:#8a6f45;
    font-family:'PT Serif', serif;
    font-size:13px;
    letter-spacing:0.06em;
}

.gg-blog-card-body{
    position:relative;
    max-width:820px;
    margin:0 auto;
    overflow:visible;

    color:#2f2b25;
    font-family:'PT Serif', serif;
    font-size:clamp(16px,1.05vw,20px);
    line-height:1.85;
    letter-spacing:0.04em;
}

.gg-blog-card-body.is-collapsed{
    max-height:9.2em;
    overflow:hidden;
}


.gg-blog-card-body h2,
.gg-blog-card-body h3{
    color:#B9965F;
    font-family:'PT Serif', serif;
    font-weight:400;
    line-height:1.35;
    margin:clamp(28px,3vw,46px) 0 12px;
}

.gg-blog-card-body h2{
    font-size:clamp(24px,2.4vw,38px);
}

.gg-blog-card-body h3{
    font-size:clamp(20px,1.8vw,30px);
}

.gg-blog-card-body p{
    margin:0 0 clamp(18px,2vw,28px);
}

.gg-blog-card-body p:last-child{
    margin-bottom:0;
}

.gg-blog-card-body a{
    color:#B9965F;
    text-decoration:none;
    border-bottom:1px solid rgba(185,150,95,0.45);
}

.gg-blog-card-body a:hover{
    border-bottom-color:#B9965F;
}

.gg-blog-card-comments{
    max-width:820px;
    margin:clamp(28px,3vw,46px) auto 0;
}

.gg-blog-inline-comments{
    margin-top:clamp(28px,3vw,46px);
    padding-top:clamp(22px,2vw,34px);
    border-top:1px solid rgba(159,133,96,0.45);
}

.gg-blog-inline-comments h3{
    margin-top:0;
}

.gg-blog-comments-notice{
    margin:0 0 18px !important;
    color:#6b7d3a !important;
    font-size:14px !important;
    letter-spacing:0.08em;
}

.gg-blog-comment-list{
    display:grid;
    gap:16px;
    margin-bottom:clamp(22px,2vw,34px);
}

.gg-blog-comment{
    padding-bottom:16px;
    border-bottom:1px solid rgba(159,133,96,0.28);
}

.gg-blog-comment strong{
    display:block;
    color:#B9965F;
    font-weight:400;
    letter-spacing:0.12em;
    text-transform:uppercase;
    font-size:12px;
    margin-bottom:6px;
}

.gg-blog-comment time{
    display:block;
    color:#8a6f45;
    font-size:12px;
    margin-bottom:8px;
}

.gg-blog-comment p{
    margin:0 !important;
    font-size:15px !important;
    line-height:1.65 !important;
}

.gg-blog-comment-form{
    display:grid;
    gap:12px;
}

.gg-blog-comment-fields{
    display:grid;
    grid-template-columns:1fr 1fr;
    gap:12px;
}

.gg-blog-comment-form input,
.gg-blog-comment-form textarea{
    width:100%;
    box-sizing:border-box;
    padding:10px 12px;
    border:1px solid rgba(159,133,96,0.75);
    background:transparent;
    color:#2f2b25;
    font-family:'PT Serif', serif;
    font-size:15px;
}

.gg-blog-comment-form textarea{
    min-height:120px;
    resize:vertical;
}

	
	
.gg-blog-comment-form input:focus,
.gg-blog-comment-form textarea:focus{
    outline:none;
    border-color:#B9965F;
}

.gg-blog-comment-form button{
    width:fit-content;
    padding:10px 18px;
    border:2px solid #aa8a58;
    color:#3a2c1f;
    background:transparent;
    font-family:Georgia, "Times New Roman", serif;
    font-size:13px;
    text-transform:uppercase;
    letter-spacing:0.08em;
    cursor:pointer;
}

.gg-blog-comment-form button:hover{
    color:#B9965F;
    border-color:#B9965F;
}

	.gg-blog-comment-field{
    position:relative;
    display:block;
    width:100%;
}

.gg-blog-comment-field input,
.gg-blog-comment-field textarea{
    display:block;
    width:100%;
}

.gg-blog-comment-field{
    position:relative;
    display:block;
    width:100%;
}

.gg-blog-comment-field input,
.gg-blog-comment-field textarea{
    display:block;
    width:100%;
}

.gg-blog-field-placeholder{
    position:absolute;
    top:10px;
    left:12px;
    color:rgba(47,43,37,0.58);
    font-family:'PT Serif', serif;
    font-size:15px;
    line-height:1.4;
    pointer-events:none;
    transition:opacity 0.18s ease, visibility 0.18s ease;
}

.gg-blog-comment-textarea-field .gg-blog-field-placeholder{
    top:12px;
}

.gg-blog-required-star{
    position:static;
    color:#8a2f2f;
    font-size:16px;
    line-height:1;
    margin-left:3px;
}

.gg-blog-comment-field input:focus + .gg-blog-field-placeholder,
.gg-blog-comment-field input:not(:placeholder-shown) + .gg-blog-field-placeholder,
.gg-blog-comment-field textarea:focus + .gg-blog-field-placeholder,
.gg-blog-comment-field textarea:not(:placeholder-shown) + .gg-blog-field-placeholder{
    opacity:0;
    visibility:hidden;
}
	
.gg-blog-search-form,
.gg-blog-price-card,
.gg-blog-cta-card,
.gg-blog-featured-card{
    display:block;
    padding:18px;
    margin-bottom:18px;
    border:1px solid rgba(159,133,96,0.65);
    color:#2f2b25;
    text-decoration:none;
    background:rgba(255,250,242,0.20);
    font-family:'PT Serif', serif;
    box-sizing:border-box;
    transition:border-color 0.25s ease, transform 0.25s ease, box-shadow 0.25s ease;
}

.gg-blog-featured-card{
    width:100%;
    text-align:left;
    cursor:pointer;
}

button.gg-blog-featured-card{
    appearance:none;
}

.gg-blog-metal-widget{
    display:block;
    padding:18px;
    margin-bottom:18px;
    border:1px solid rgba(159,133,96,0.65);
    color:#2f2b25;
    background:rgba(255,250,242,0.20);
    font-family:'PT Serif', serif;
    box-sizing:border-box;
}

.gg-blog-metal-widget-head{
    margin-bottom:14px;
    padding-bottom:14px;
    border-bottom:1px solid rgba(159,133,96,0.45);
}

.gg-blog-metal-widget-head span{
    display:block;
    margin-bottom:8px;
    color:#B9965F;
    font-size:12px;
    letter-spacing:0.18em;
    text-transform:uppercase;
}

.gg-blog-metal-widget-head strong{
    display:block;
    margin-bottom:8px;
    color:#2f2b25;
    font-size:clamp(18px,1.3vw,24px);
    font-weight:400;
    line-height:1.35;
}

.gg-blog-metal-widget-head small{
    display:block;
    color:#2f2b25;
    font-size:14px;
    line-height:1.6;
}

.gg-blog-metal-row{
    display:grid;
    grid-template-columns:1fr;
    gap:4px;
    padding:13px 0;
    color:#2f2b25;
    text-decoration:none;
    border-bottom:1px solid rgba(159,133,96,0.32);
    transition:color 0.25s ease, transform 0.25s ease;
}

.gg-blog-metal-row:last-child{
    border-bottom:0;
    padding-bottom:0;
}

.gg-blog-metal-row > span{
    color:#B9965F;
    font-size:12px;
    letter-spacing:0.18em;
    text-transform:uppercase;
}

.gg-blog-metal-price{
    display:flex;
    align-items:baseline;
    flex-wrap:wrap;
    gap:8px;
    color:#2f2b25;
    font-weight:400;
    line-height:1.2;
}

.gg-blog-metal-price-number{
    color:#2f2b25;
    font-size:clamp(22px,1.7vw,32px);
    font-weight:400;
}

.gg-blog-metal-price-unit{
    color:#B9965F;
    font-size:12px;
    letter-spacing:0.18em;
    text-transform:uppercase;
    font-weight:400;
}

.gg-blog-metal-row small{
    color:#8a6f45;
    font-size:13px;
    line-height:1.45;
}

.gg-blog-metal-row:hover{
    transform:translateX(3px);
}

.gg-blog-metal-row:hover .gg-blog-metal-price-number{
    color:#B9965F;
}

.gg-blog-metal-change-up{
    color:#6b7d3a !important;
}

.gg-blog-metal-change-down{
    color:#8a4f3c !important;
}

.gg-blog-search-box{
    display:grid;
    grid-template-columns:1fr auto;
    gap:8px;
}

.gg-blog-search-box input{
    width:100%;
    min-width:0;
    box-sizing:border-box;
    padding:11px 12px;
    border:1px solid rgba(159,133,96,0.75);
    background:transparent;
    color:#2f2b25;
    font-family:'PT Serif', serif;
    font-size:15px;
}

.gg-blog-search-box input:focus{
    outline:none;
    border-color:#B9965F;
}

.gg-blog-search-box button{
    width:42px;
    border:1px solid #B9965F;
    background:transparent;
    color:#B9965F;
    cursor:pointer;
    font-family:'PT Serif', serif;
    font-size:22px;
    line-height:1;
}

.gg-blog-search-box button:hover{
    color:#2f2b25;
}

.gg-blog-price-card span,
.gg-blog-cta-card span,
.gg-blog-featured-card span{
    display:block;
    margin-bottom:8px;
    color:#B9965F;
    font-size:12px;
    letter-spacing:0.18em;
    text-transform:uppercase;
}

.gg-blog-price-card strong,
.gg-blog-cta-card strong,
.gg-blog-featured-card strong{
    display:block;
    margin-bottom:8px;
    font-size:clamp(18px,1.3vw,24px);
    font-weight:400;
    line-height:1.35;
}

.gg-blog-price-card small,
.gg-blog-cta-card small,
.gg-blog-featured-card small{
    display:block;
    color:#2f2b25;
    font-size:14px;
    line-height:1.6;
}

.gg-blog-price-card:hover,
.gg-blog-cta-card:hover,
.gg-blog-featured-card:hover{
    border-color:#B9965F;
    transform:translateY(-1px);
    box-shadow:0 6px 16px rgba(80,55,30,0.06);
}

.gg-blog-load-more{
    width:100%;
    margin-top:clamp(24px,3vw,42px);
    padding:12px 18px;
    border:2px solid #aa8a58;
    color:#3a2c1f;
    background:transparent;
    font-family:Georgia, "Times New Roman", serif;
    font-size:clamp(12px,0.8vw,15px);
    text-transform:uppercase;
    letter-spacing:0.08em;
    cursor:pointer;
}

.gg-blog-load-more:hover{
    color:#B9965F;
    border-color:#B9965F;
}

.gg-blog-load-more[disabled]{
    opacity:0.45;
    cursor:not-allowed;
}

.gg-blog-empty{
    color:#2f2b25;
    font-family:'PT Serif', serif;
    font-size:18px;
    line-height:1.7;
}

.gg-blog-sentinel{
    height:1px;
}
	
	.screen-reader-text{
    position:absolute !important;
    width:1px;
    height:1px;
    padding:0;
    margin:-1px;
    overflow:hidden;
    clip:rect(0,0,0,0);
    white-space:nowrap;
    border:0;
}

@media(max-width:980px){
    .gg-blog-layout{
        grid-template-columns:1fr;
    }

    .gg-blog-topics,
    .gg-blog-info{
        position:static;
    }

    .gg-blog-topics{
        display:block;
    }

    .gg-blog-side-title{
        width:100%;
    }

    .gg-blog-topic{
        width:fit-content;
        margin-bottom:14px;
    }

    .gg-blog-card-header{
    padding:24px 20px 18px;
}

.gg-blog-card-content{
    padding:24px 20px;
}
}

@media(max-width:700px){
    .gg-blog-page{
        padding:40px 5%;
    }

    .gg-blog-heading{
        gap:12px;
    }

    .gg-blog-heading h1{
        font-size:17px;
        letter-spacing:0.13em;
    }

    .gg-blog-intro{
        text-align:left;
    }

    .gg-blog-card-meta{
        flex-direction:column;
    }

    .gg-blog-comment-fields{
        grid-template-columns:1fr;
    }
	.gg-blog-card-header{
    padding:24px 20px 18px;
}
	
	.gg-blog-card-image-wrap{
    width:92%;
}

.gg-blog-card-image{
    max-height:none;
}

.gg-blog-card-header h2{
    text-align:left;
}

.gg-blog-card-content{
    padding:24px 20px;
}

.gg-blog-card-excerpt{
    text-align:left;
}

.gg-blog-card-meta{
    justify-content:flex-start;
}
	
}
</style>

<script>
document.addEventListener('DOMContentLoaded', function() {
    const app = document.getElementById('gg-blog-app');

    if (!app) return;

    const results = document.getElementById('gg-blog-results');
    const loadMore = document.getElementById('gg-blog-load-more');
    const searchInput = document.getElementById('gg-blog-search');
    const searchForm = document.querySelector('.gg-blog-search-form');
    const hiddenTopic = document.getElementById('gg-blog-search-topic');
    const sentinel = document.getElementById('gg-blog-sentinel');

    let page = parseInt(app.dataset.page, 10) || 1;
    let maxPages = parseInt(app.dataset.maxPages, 10) || 1;
    let postsPerPage = parseInt(app.dataset.postsPerPage, 10) || 6;
    let topic = hiddenTopic ? hiddenTopic.value : '';
    let search = searchInput ? searchInput.value.trim() : '';
    let loading = false;
    let searchTimer = null;
    let articleLoading = {};

    function setActiveTopic(activeLink) {
        document.querySelectorAll('.gg-blog-topic').forEach(function(link) {
            link.classList.remove('active');
            link.setAttribute('aria-pressed', 'false');
        });

        activeLink.classList.add('active');
        activeLink.setAttribute('aria-pressed', 'true');
    }

    function updateUrl() {
        if (!window.history || !window.URL) return;

        const url = new URL(window.location.href);

        if (topic) {
            url.searchParams.set('gg_blog_topic', topic);
        } else {
            url.searchParams.delete('gg_blog_topic');
        }

        if (search) {
            url.searchParams.set('gg_blog_search', search);
        } else {
            url.searchParams.delete('gg_blog_search');
        }

        window.history.replaceState({}, '', url.toString());
    }

    function ggBlogFormatSekGram(value) {
        return new Intl.NumberFormat('sv-SE', {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2
        }).format(value);
    }

    function ggBlogFormatChange(value) {
        const sign = value > 0 ? '+': '';

        return sign + new Intl.NumberFormat('sv-SE', {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2
        }).format(value) + '% idag';
    }

    function ggBlogSetMetalChange(id, value) {
        const el = document.getElementById(id);

        if (!el) return;

        el.textContent = (value >= 0 ? '▲ ' : '▼ ') + ggBlogFormatChange(value);
        el.classList.remove('gg-blog-metal-change-up', 'gg-blog-metal-change-down');
        el.classList.add(value >= 0 ? 'gg-blog-metal-change-up' : 'gg-blog-metal-change-down');
    }

    async function ggBlogGetTVQuote(symbol) {
        const url = 'https://scanner.tradingview.com/symbol?symbol=' +
            encodeURIComponent(symbol) +
            '&fields=close,change';

        const response = await fetch(url);
        const data = await response.json();

        if (!data || typeof data.close !== 'number') {
            throw new Error('Kunde inte hämta ' + symbol);
        }

        return {
            close: data.close,
            change: typeof data.change === 'number' ? data.change : 0
        };
    }

    async function ggBlogUpdateMetalPrices() {
        const goldPriceEl = document.getElementById('gg-blog-gold-sek-g');
        const silverPriceEl = document.getElementById('gg-blog-silver-sek-g');

        if (!goldPriceEl || !silverPriceEl) return;

        const gramPerOz = 31.1034768;

        try {
            const gold = await ggBlogGetTVQuote('TVC:GOLD');
            const silver = await ggBlogGetTVQuote('TVC:SILVER');
            const usdSek = await ggBlogGetTVQuote('FX_IDC:USDSEK');

            const goldSekG = (gold.close * usdSek.close) / gramPerOz;
            const silverSekG = (silver.close * usdSek.close) / gramPerOz;

            goldPriceEl.textContent = ggBlogFormatSekGram(goldSekG);
            silverPriceEl.textContent = ggBlogFormatSekGram(silverSekG);

            ggBlogSetMetalChange('gg-blog-gold-change', gold.change + usdSek.change);
            ggBlogSetMetalChange('gg-blog-silver-change', silver.change + usdSek.change);

        } catch (error) {
            goldPriceEl.textContent = '—';
            silverPriceEl.textContent = '—';

            const goldChangeEl = document.getElementById('gg-blog-gold-change');
            const silverChangeEl = document.getElementById('gg-blog-silver-change');

            if (goldChangeEl) {
                goldChangeEl.textContent = 'Se guldprissidan';
            }

            if (silverChangeEl) {
                silverChangeEl.textContent = 'Se silverprissidan';
            }
        }
    }

    function updateLoadButton() {
        if (!loadMore) return;

        if (page >= maxPages || maxPages < 2) {
            loadMore.style.display = 'none';
        } else {
            loadMore.style.display = 'block';
        }
    }

  function ggBlogOpenInlineArticle(card, scrollToCard) {
    if (!card) return;

    const postId = card.dataset.postId;
    const button = card.querySelector('.gg-blog-read-more');
    const body = card.querySelector('.gg-blog-card-body');
    const commentsBox = card.querySelector('.gg-blog-card-comments');

    if (!postId || !button || !body || !commentsBox) return;

    const collapsesContent = button.dataset.collapsesContent === '1';
    const isExpanded = card.classList.contains('is-expanded');

    if (isExpanded) {
        card.classList.remove('is-expanded');

        if (collapsesContent) {
            body.classList.add('is-collapsed');
            button.textContent = 'Läs hela artikeln';
        } else {
            button.textContent = 'Visa kommentarer';
        }

        commentsBox.hidden = true;
        button.setAttribute('aria-expanded', 'false');

        return;
    }

    card.classList.add('is-expanded');

    if (collapsesContent) {
        body.classList.remove('is-collapsed');
        button.textContent = 'Stäng artikeln';
    } else {
        button.textContent = 'Stäng kommentarer';
    }

    button.setAttribute('aria-expanded', 'true');

    if (commentsBox.dataset.loaded === '1') {
        commentsBox.hidden = false;

        if (scrollToCard) {
            card.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }

        return;
    }

    button.disabled = true;

    const formData = new FormData();
    formData.append('action', 'gg_blog_load_inline_comments');
    formData.append('nonce', app.dataset.nonce);
    formData.append('post_id', postId);

    fetch(app.dataset.ajaxUrl, {
        method: 'POST',
        body: formData,
        credentials: 'same-origin'
    })
    .then(function(response) {
        return response.json();
    })
    .then(function(data) {
        if (!data || !data.success) {
            throw new Error('Kunde inte ladda kommentarer.');
        }

        commentsBox.innerHTML = data.data.html;
        commentsBox.dataset.loaded = '1';
        commentsBox.hidden = false;

        if (scrollToCard) {
            card.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
    })
    .catch(function() {
        commentsBox.innerHTML = '<p>Kunde inte ladda kommentarer just nu.</p>';
        commentsBox.hidden = false;
    })
    .finally(function() {
        button.disabled = false;
    });
}

    function ggBlogLoadFeaturedCard(postId) {
        let existingCard = document.querySelector('.gg-blog-card[data-post-id="' + postId + '"]');

        if (existingCard) {
            ggBlogOpenInlineArticle(existingCard, true);
            return;
        }

        const formData = new FormData();
        formData.append('action', 'gg_blog_load_single_card');
        formData.append('nonce', app.dataset.nonce);
        formData.append('post_id', postId);

        fetch(app.dataset.ajaxUrl, {
            method: 'POST',
            body: formData,
            credentials: 'same-origin'
        })
        .then(function(response) {
            return response.json();
        })
        .then(function(data) {
            if (!data || !data.success) {
                throw new Error('Kunde inte ladda artikeln.');
            }

            results.insertAdjacentHTML('afterbegin', data.data.html);

            existingCard = document.querySelector('.gg-blog-card[data-post-id="' + postId + '"]');

            if (existingCard) {
                ggBlogOpenInlineArticle(existingCard, true);
            }
        });
    }

    function loadPosts(reset) {
        if (loading) return;

        loading = true;

        if (loadMore) {
            loadMore.disabled = true;
            loadMore.textContent = 'Laddar...';
        }

        const nextPage = reset ? 1 : page + 1;

        const formData = new FormData();
        formData.append('action', 'gg_blog_load_posts');
        formData.append('nonce', app.dataset.nonce);
        formData.append('page', nextPage);
        formData.append('topic', topic);
        formData.append('search', search);
        formData.append('posts_per_page', postsPerPage);

        fetch(app.dataset.ajaxUrl, {
            method: 'POST',
            body: formData,
            credentials: 'same-origin'
        })
        .then(function(response) {
            return response.json();
        })
        .then(function(data) {
            if (!data || !data.success) {
                throw new Error('Kunde inte ladda artiklar.');
            }

            if (reset) {
                results.innerHTML = data.data.html;
            } else {
                results.insertAdjacentHTML('beforeend', data.data.html);
            }

            page = parseInt(data.data.page, 10) || 1;
            maxPages = parseInt(data.data.max_pages, 10) || 1;

            updateLoadButton();
            updateUrl();
        })
        .catch(function() {
            if (reset) {
                results.innerHTML = '<p class="gg-blog-empty">Kunde inte ladda artiklar just nu.</p>';
            }
        })
        .finally(function() {
            loading = false;

            if (loadMore) {
                loadMore.disabled = false;
                loadMore.textContent = 'Ladda fler artiklar';
            }
        });
    }

    document.addEventListener('click', function(e) {
        const topicLink = e.target.closest('.gg-blog-topic');

        if (!topicLink) return;

        e.preventDefault();

        topic = topicLink.dataset.topic || '';

        if (hiddenTopic) {
            hiddenTopic.value = topic;
        }

        setActiveTopic(topicLink);
        loadPosts(true);
    });

    document.addEventListener('click', function(e) {
        const readMore = e.target.closest('.gg-blog-read-more');

        if (!readMore) return;

        e.preventDefault();

        const card = readMore.closest('.gg-blog-card');

        ggBlogOpenInlineArticle(card, false);
    });

    document.addEventListener('click', function(e) {
        const featured = e.target.closest('.gg-blog-featured-open');

        if (!featured) return;

        e.preventDefault();

        const postId = featured.dataset.postId;

        if (postId) {
            ggBlogLoadFeaturedCard(postId);
        }
    });

    document.addEventListener('submit', function(e) {
        const form = e.target.closest('.gg-blog-comment-form');

        if (!form) return;

        e.preventDefault();

        const wrap = form.closest('.gg-blog-comments-wrap');
        const card = form.closest('.gg-blog-card');
        const button = form.querySelector('button[type="submit"]');

        if (button) {
            button.disabled = true;
            button.textContent = 'Skickar...';
        }

        const formData = new FormData(form);
        formData.append('action', 'gg_blog_submit_comment');
        formData.append('nonce', app.dataset.nonce);

        fetch(app.dataset.ajaxUrl, {
            method: 'POST',
            body: formData,
            credentials: 'same-origin'
        })
        .then(function(response) {
            return response.json();
        })
        .then(function(data) {
            if (!data || !data.success) {
                throw new Error(data && data.data && data.data.message ? data.data.message : 'Kommentaren kunde inte skickas.');
            }

            if (wrap && data.data.comments_html) {
                wrap.outerHTML = data.data.comments_html;
            }

            if (card && data.data.comment_count) {
                const countEl = card.querySelector('.gg-blog-comment-count');

                if (countEl) {
                    countEl.textContent = data.data.comment_count;
                }
            }
        })
        .catch(function(error) {
            const notice = form.querySelector('.gg-blog-comments-notice');

            if (notice) {
                notice.textContent = error.message;
            } else {
                form.insertAdjacentHTML('beforebegin', '<p class="gg-blog-comments-notice">' + error.message + '</p>');
            }
        })
        .finally(function() {
            if (button) {
                button.disabled = false;
                button.textContent = 'Publicera kommentar';
            }
        });
    });

    if (searchInput) {
        searchInput.addEventListener('input', function() {
            clearTimeout(searchTimer);

            searchTimer = setTimeout(function() {
                search = searchInput.value.trim();
                loadPosts(true);
            }, 350);
        });
    }

    if (searchForm) {
        searchForm.addEventListener('submit', function(e) {
            e.preventDefault();

            search = searchInput ? searchInput.value.trim() : '';
            loadPosts(true);
        });
    }

    if (loadMore) {
        loadMore.addEventListener('click', function() {
            loadPosts(false);
        });
    }

    if ('IntersectionObserver' in window && sentinel) {
        const observer = new IntersectionObserver(function(entries) {
            entries.forEach(function(entry) {
                if (entry.isIntersecting && page < maxPages && !loading) {
                    loadPosts(false);
                }
            });
        }, {
            rootMargin: '320px'
        });

        observer.observe(sentinel);
    }

    ggBlogUpdateMetalPrices();
    updateLoadButton();
});
</script>

    <?php
    return ob_get_clean();
}

function gg_blog_get_query_args($page, $posts_per_page, $topic = '', $search = '') {

    $args = [
        'post_type'           => 'gg_blog_post',
        'post_status'         => 'publish',
        'posts_per_page'      => max(1, absint($posts_per_page)),
        'paged'               => max(1, absint($page)),
        'orderby'             => 'date',
        'order'               => 'DESC',
        'ignore_sticky_posts' => true,
    ];

    if ($search !== '') {
        $args['s'] = sanitize_text_field($search);
    }

    if ($topic !== '') {
        $args['tax_query'] = [
            [
                'taxonomy' => 'gg_blog_topic',
                'field'    => 'slug',
                'terms'    => sanitize_title($topic),
            ],
        ];
    }

    return $args;
}

function gg_blog_get_clean_excerpt($post_id, $words = 42) {

    $manual_excerpt = get_post_field('post_excerpt', $post_id);
    $source = $manual_excerpt ? $manual_excerpt : get_post_field('post_content', $post_id);

    $source = strip_shortcodes($source);
    $source = str_replace('<!--more-->', ' ', $source);
    $source = wp_strip_all_tags($source, true);

    return wp_trim_words($source, $words);
}

function gg_blog_get_plain_content_length($post_id) {

    $content = get_post_field('post_content', $post_id);
    $content = strip_shortcodes($content);
    $content = str_replace('<!--more-->', ' ', $content);
    $content = wp_strip_all_tags($content, true);
    $content = preg_replace('/\s+/u', ' ', trim($content));

    if (function_exists('mb_strlen')) {
        return mb_strlen($content, 'UTF-8');
    }

    return strlen($content);
}

function gg_blog_extract_first_image_html_from_content($content) {

    if (function_exists('parse_blocks')) {
        $blocks = parse_blocks($content);
        $image_html = gg_blog_find_first_image_block_html($blocks);

        if ($image_html) {
            return wp_kses_post($image_html);
        }
    }

    if (preg_match('/<figure[^>]*class="[^"]*wp-block-image[^"]*"[^>]*>.*?<\/figure>/is', $content, $matches)) {
        return wp_kses_post($matches[0]);
    }

    if (preg_match('/<img[^>]+>/i', $content, $matches)) {
        return wp_kses_post($matches[0]);
    }

    return '';
}

function gg_blog_find_first_image_block_html($blocks) {

    foreach ($blocks as $block) {
        if (!empty($block['blockName']) && $block['blockName'] === 'core/image') {
            return render_block($block);
        }

        if (!empty($block['innerBlocks'])) {
            $nested_image = gg_blog_find_first_image_block_html($block['innerBlocks']);

            if ($nested_image) {
                return $nested_image;
            }
        }
    }

    return '';
}

function gg_blog_remove_first_content_image($content) {

    $updated_content = preg_replace('/<!-- wp:image[^>]*-->.*?<!-- \/wp:image -->/is', '', $content, 1, $count);

    if ($count > 0) {
        return $updated_content;
    }

    $updated_content = preg_replace('/<figure[^>]*class="[^"]*wp-block-image[^"]*"[^>]*>.*?<\/figure>/is', '', $content, 1, $count);

    if ($count > 0) {
        return $updated_content;
    }

    return preg_replace('/<img[^>]+>/i', '', $content, 1);
}

function gg_blog_get_card_image_html($post_id) {

    $image_id = get_post_thumbnail_id($post_id);

    if ($image_id) {
        return wp_get_attachment_image($image_id, 'large', false, [
            'class'    => 'gg-blog-card-image',
            'loading'  => 'lazy',
            'decoding' => 'async',
        ]);
    }

    $content = get_post_field('post_content', $post_id);

    return gg_blog_extract_first_image_html_from_content($content);
}

function gg_blog_get_inline_article_content($post_id, $remove_first_image = false) {

    global $post;

    $old_post = $post;
    $post = get_post($post_id);

    if ($post) {
        setup_postdata($post);
    }

    $content = get_post_field('post_content', $post_id);
    $content = str_replace('<!--more-->', '', $content);

    if ($remove_first_image) {
        $content = gg_blog_remove_first_content_image($content);
    }

    $content = apply_filters('the_content', $content);

    wp_reset_postdata();

    $post = $old_post;

    return wp_kses_post($content);
}

function gg_blog_render_card($post_id) {

    $topics = get_the_terms($post_id, 'gg_blog_topic');
    $topic_name = '';

    if (!is_wp_error($topics) && !empty($topics)) {
        $topic_name = $topics[0]->name;
    }

    $reading_time = get_post_meta($post_id, '_gg_blog_reading_time', true);

    if (!$reading_time) {
        $reading_time = gg_blog_estimate_reading_time($post_id);
    }

    $comment_count = gg_blog_get_comment_count_label($post_id);

    $has_thumbnail = (bool) get_post_thumbnail_id($post_id);
    $card_image_html = gg_blog_get_card_image_html($post_id);
    $remove_first_content_image = (!$has_thumbnail && $card_image_html !== '');

    $content_length = gg_blog_get_plain_content_length($post_id);
    $is_long_article = $content_length > 250;
    $has_comment_area = comments_open($post_id) || get_comments_number($post_id) > 0;
    ?>

    <article class="gg-blog-card" data-post-id="<?php echo esc_attr($post_id); ?>">

        <header class="gg-blog-card-header">
            <?php if ($topic_name) : ?>
                <span class="gg-blog-card-topic"><?php echo esc_html($topic_name); ?></span>
            <?php endif; ?>

            <h2><?php echo esc_html(get_the_title($post_id)); ?></h2>
        </header>

        <?php if ($card_image_html) : ?>
            <div class="gg-blog-card-image-wrap">
                <?php echo $card_image_html; ?>
            </div>
        <?php endif; ?>

        <div class="gg-blog-card-content">

            <div class="gg-blog-card-body <?php echo $is_long_article ? 'is-collapsed' : ''; ?>">
                <?php echo gg_blog_get_inline_article_content($post_id, $remove_first_content_image); ?>
            </div>

            <?php if ($is_long_article || $has_comment_area) : ?>
                <button
                    type="button"
                    class="gg-blog-read-more"
                    data-post-id="<?php echo esc_attr($post_id); ?>"
                    data-collapses-content="<?php echo $is_long_article ? '1' : '0'; ?>"
                    aria-expanded="false"
                >
                    <?php echo $is_long_article ? 'Läs hela artikeln' : 'Visa kommentarer'; ?>
                </button>
            <?php endif; ?>

            <div class="gg-blog-card-meta">
                <span><?php echo esc_html(get_the_date('j F Y', $post_id)); ?></span>
                <span><?php echo esc_html($reading_time); ?></span>
                <span class="gg-blog-comment-count"><?php echo esc_html($comment_count); ?></span>
            </div>

            <div class="gg-blog-card-comments" hidden></div>

        </div>

    </article>

    <?php
}

function gg_blog_estimate_reading_time($post_id) {

    $content = wp_strip_all_tags(get_post_field('post_content', $post_id));
    $words = str_word_count($content);
    $minutes = max(1, ceil($words / 220));

    return $minutes . ' min läsning';
}

function gg_blog_get_comment_count_label($post_id) {

    $comment_count = (int) get_comments_number($post_id);

    return number_format_i18n($comment_count) . ' kommentarer';
}

function gg_blog_render_featured_widget() {

    $featured_query = new WP_Query([
        'post_type'           => 'gg_blog_post',
        'post_status'         => 'publish',
        'posts_per_page'      => 1,
        'ignore_sticky_posts' => true,
        'meta_query'          => [
            [
                'key'   => '_gg_blog_featured',
                'value' => '1',
            ],
        ],
    ]);

    if (!$featured_query->have_posts()) {
        return;
    }

    while ($featured_query->have_posts()) :
        $featured_query->the_post();

        $post_id = get_the_ID();
        $excerpt = gg_blog_get_clean_excerpt($post_id, 18);
        ?>

        <button
            type="button"
            class="gg-blog-featured-card gg-blog-featured-open"
            data-post-id="<?php echo esc_attr($post_id); ?>"
        >
            <span>Utvald artikel</span>
            <strong><?php echo esc_html(get_the_title($post_id)); ?></strong>
            <small><?php echo esc_html($excerpt); ?></small>
        </button>

        <?php
    endwhile;

    wp_reset_postdata();
}

function gg_blog_render_inline_comments($post_id, $notice = '') {

    $comments = get_comments([
        'post_id' => $post_id,
        'status'  => 'approve',
        'order'   => 'ASC',
    ]);

    $current_user = wp_get_current_user();
    $is_logged_in = is_user_logged_in();

    ob_start();
    ?>

    <div class="gg-blog-comments-wrap" data-post-id="<?php echo esc_attr($post_id); ?>">

        <div class="gg-blog-inline-comments">
            <h3>Kommentarer</h3>

            <?php if ($notice) : ?>
                <p class="gg-blog-comments-notice"><?php echo esc_html($notice); ?></p>
            <?php endif; ?>

            <?php if (!empty($comments)) : ?>
                <div class="gg-blog-comment-list">
                    <?php foreach ($comments as $comment) : ?>
                        <div class="gg-blog-comment">
                            <strong><?php echo esc_html(get_comment_author($comment)); ?></strong>
                            <time><?php echo esc_html(get_comment_date('j F Y', $comment)); ?></time>
                            <p><?php echo esc_html(wp_strip_all_tags($comment->comment_content)); ?></p>
                        </div>
                    <?php endforeach; ?>
                </div>
            <?php else : ?>
                <p>Inga kommentarer ännu.</p>
            <?php endif; ?>

            <?php if (comments_open($post_id)) : ?>
                <form class="gg-blog-comment-form">
                    <input type="hidden" name="post_id" value="<?php echo esc_attr($post_id); ?>">

                    <?php if (!$is_logged_in) : ?>
    <div class="gg-blog-comment-fields">
        <label class="gg-blog-comment-field gg-blog-comment-field-required">
    <span class="screen-reader-text">Namn, obligatoriskt</span>
    <input type="text" name="author" placeholder=" " required>
    <span class="gg-blog-field-placeholder">
        Namn <span class="gg-blog-required-star" aria-hidden="true">*</span>
    </span>
</label>

<label class="gg-blog-comment-field">
    <span class="screen-reader-text">E-post, valfri</span>
    <input type="email" name="email" placeholder=" ">
    <span class="gg-blog-field-placeholder">
        E-post (valfri)
    </span>
</label>
    </div>
<?php else : ?>
                        <p>
                            Inloggad som <?php echo esc_html($current_user->display_name); ?>.
                        </p>
                    <?php endif; ?>

            <label class="gg-blog-comment-field gg-blog-comment-textarea-field gg-blog-comment-field-required">
    <span class="screen-reader-text">Kommentar, obligatorisk</span>
    <textarea name="comment" placeholder=" " required></textarea>
    <span class="gg-blog-field-placeholder">
        Skriv en kommentar <span class="gg-blog-required-star" aria-hidden="true">*</span>
    </span>
</label>

                    <button type="submit">Publicera kommentar</button>
                </form>
            <?php else : ?>
                <p>Kommentarer är stängda för den här artikeln.</p>
            <?php endif; ?>
        </div>

    </div>

    <?php

    return ob_get_clean();
}

add_action('wp_ajax_gg_blog_load_posts', 'gg_blog_load_posts');
add_action('wp_ajax_nopriv_gg_blog_load_posts', 'gg_blog_load_posts');

function gg_blog_load_posts() {

    if (!post_type_exists('gg_blog_post') || !taxonomy_exists('gg_blog_topic')) {
        wp_send_json_error([
            'message' => 'Bloggen är inte aktiverad.',
        ], 400);
    }

    if (
        empty($_POST['nonce']) ||
        !wp_verify_nonce(sanitize_text_field(wp_unslash($_POST['nonce'])), 'gg_blog_load_posts')
    ) {
        wp_send_json_error([
            'message' => 'Säkerhetskontrollen misslyckades.',
        ], 403);
    }

    $page = isset($_POST['page'])
        ? max(1, absint($_POST['page']))
        : 1;

    $posts_per_page = isset($_POST['posts_per_page'])
        ? max(1, min(12, absint($_POST['posts_per_page'])))
        : 6;

    $topic = isset($_POST['topic'])
        ? sanitize_title(wp_unslash($_POST['topic']))
        : '';

    $search = isset($_POST['search'])
        ? sanitize_text_field(wp_unslash($_POST['search']))
        : '';

    $query = new WP_Query(gg_blog_get_query_args($page, $posts_per_page, $topic, $search));

    ob_start();

    if ($query->have_posts()) {
        while ($query->have_posts()) {
            $query->the_post();
            gg_blog_render_card(get_the_ID());
        }

        wp_reset_postdata();
    } else {
        echo '<p class="gg-blog-empty">Inga artiklar matchade filtret.</p>';
    }

    $html = ob_get_clean();

    wp_send_json_success([
        'html'      => $html,
        'page'      => $page,
        'max_pages' => (int) $query->max_num_pages,
    ]);
}

add_action('wp_ajax_gg_blog_load_single_card', 'gg_blog_load_single_card');
add_action('wp_ajax_nopriv_gg_blog_load_single_card', 'gg_blog_load_single_card');

function gg_blog_load_single_card() {

    if (
        empty($_POST['nonce']) ||
        !wp_verify_nonce(sanitize_text_field(wp_unslash($_POST['nonce'])), 'gg_blog_load_posts')
    ) {
        wp_send_json_error([
            'message' => 'Säkerhetskontrollen misslyckades.',
        ], 403);
    }

    $post_id = isset($_POST['post_id'])
        ? absint($_POST['post_id'])
        : 0;

    if (!$post_id || get_post_type($post_id) !== 'gg_blog_post' || get_post_status($post_id) !== 'publish') {
        wp_send_json_error([
            'message' => 'Artikeln hittades inte.',
        ], 404);
    }

    ob_start();
    gg_blog_render_card($post_id);
    $html = ob_get_clean();

    wp_send_json_success([
        'html' => $html,
    ]);
}

add_action('wp_ajax_gg_blog_load_inline_comments', 'gg_blog_load_inline_comments');
add_action('wp_ajax_nopriv_gg_blog_load_inline_comments', 'gg_blog_load_inline_comments');

function gg_blog_load_inline_comments() {

    if (
        empty($_POST['nonce']) ||
        !wp_verify_nonce(sanitize_text_field(wp_unslash($_POST['nonce'])), 'gg_blog_load_posts')
    ) {
        wp_send_json_error([
            'message' => 'Säkerhetskontrollen misslyckades.',
        ], 403);
    }

    $post_id = isset($_POST['post_id'])
        ? absint($_POST['post_id'])
        : 0;

    if (!$post_id || get_post_type($post_id) !== 'gg_blog_post' || get_post_status($post_id) !== 'publish') {
        wp_send_json_error([
            'message' => 'Artikeln hittades inte.',
        ], 404);
    }

    wp_send_json_success([
        'html' => gg_blog_render_inline_comments($post_id),
    ]);
}

add_action('wp_ajax_gg_blog_submit_comment', 'gg_blog_submit_comment');
add_action('wp_ajax_nopriv_gg_blog_submit_comment', 'gg_blog_submit_comment');

function gg_blog_submit_comment() {

    if (
        empty($_POST['nonce']) ||
        !wp_verify_nonce(sanitize_text_field(wp_unslash($_POST['nonce'])), 'gg_blog_load_posts')
    ) {
        wp_send_json_error([
            'message' => 'Säkerhetskontrollen misslyckades.',
        ], 403);
    }

    $post_id = isset($_POST['post_id'])
        ? absint($_POST['post_id'])
        : 0;

    if (!$post_id || get_post_type($post_id) !== 'gg_blog_post' || get_post_status($post_id) !== 'publish') {
        wp_send_json_error([
            'message' => 'Artikeln hittades inte.',
        ], 404);
    }

    if (!comments_open($post_id)) {
        wp_send_json_error([
            'message' => 'Kommentarer är stängda för den här artikeln.',
        ], 400);
    }

    $comment_content = isset($_POST['comment'])
        ? trim(sanitize_textarea_field(wp_unslash($_POST['comment'])))
        : '';

    if ($comment_content === '') {
        wp_send_json_error([
            'message' => 'Skriv en kommentar först.',
        ], 400);
    }

    $is_logged_in = is_user_logged_in();
    $current_user = wp_get_current_user();

    if ($is_logged_in) {
        $author = $current_user->display_name;
        $email = $current_user->user_email;
        $user_id = $current_user->ID;
    } else {
        $author = isset($_POST['author'])
            ? sanitize_text_field(wp_unslash($_POST['author']))
            : '';

        $email = isset($_POST['email'])
            ? sanitize_email(wp_unslash($_POST['email']))
            : '';

        $user_id = 0;

        if (get_option('require_name_email') && ($author === '' || $email === '')) {
            wp_send_json_error([
                'message' => 'Fyll i namn och e-post.',
            ], 400);
        }

        if ($author === '') {
            $author = 'Anonym';
        }
    }

    $commentdata = [
        'comment_post_ID'      => $post_id,
        'comment_author'       => $author,
        'comment_author_email' => $email,
        'comment_content'      => $comment_content,
        'comment_type'         => '',
        'user_id'              => $user_id,
    ];

    $comment_id = wp_new_comment($commentdata, true);

    if (is_wp_error($comment_id)) {
        wp_send_json_error([
            'message' => $comment_id->get_error_message(),
        ], 400);
    }

    $comment = get_comment($comment_id);
    $notice = $comment && $comment->comment_approved === '1'
        ? 'Kommentaren är publicerad.'
        : 'Tack! Kommentaren inväntar granskning.';

    wp_send_json_success([
        'comments_html' => gg_blog_render_inline_comments($post_id, $notice),
        'comment_count' => gg_blog_get_comment_count_label($post_id),
    ]);
}

add_action('template_redirect', 'gg_blog_redirect_single_posts_to_blog');

function gg_blog_redirect_single_posts_to_blog() {

    if (is_admin() || !is_singular('gg_blog_post')) {
        return;
    }

    wp_safe_redirect(home_url('/blog/'), 302);
    exit;
}

/**
 * Gold Goblins - Block empty admin-ajax requests
 */
/**
 * Gold Goblins - Block empty admin-ajax requests
 */
add_action('admin_init', function() {
    if (!wp_doing_ajax()) {
        return;
    }

    $action = '';

    if (isset($_REQUEST['action']) && is_scalar($_REQUEST['action'])) {
        $action = sanitize_key(wp_unslash((string) $_REQUEST['action']));
    }

    if ($action !== '') {
        return;
    }

    status_header(400);
    nocache_headers();

    wp_die('Bad request', 'Bad request', [
        'response' => 400,
    ]);
}, 0);

/**
 * Gold Goblins AI Design Slider
 */
/**
 * Gold Goblins AI Design Slider
 * Shortcode: [gg_ai_design_slider]
 */
add_shortcode('gg_ai_design_slider', function($atts) {
    $atts = shortcode_atts([
        'limit' => 6,
    ], $atts);

    $limit = max(1, min(12, absint($atts['limit'])));

    $query = new WP_Query([
        'post_type'              => 'gg_customer_design',
        'post_status'            => 'publish',
        'posts_per_page'         => $limit,
        'orderby'                => 'date',
        'order'                  => 'DESC',
        'ignore_sticky_posts'    => true,
        'no_found_rows'          => true,
        'update_post_term_cache' => false,
        'meta_query'             => [
            'relation' => 'AND',
            [
                'key'     => '_gg_design_ai_image_url',
                'value'   => '',
                'compare' => '!=',
            ],
            [
                'relation' => 'OR',
                [
                    'key'     => '_gg_design_source',
                    'compare' => 'NOT EXISTS',
                ],
                [
                    'key'     => '_gg_design_source',
                    'value'   => 'ai_slider_reuse',
                    'compare' => '!=',
                ],
            ],
        ],
    ]);

    if (!$query->have_posts()) {
        return '';
    }

    $slider_id = 'gg-ai-design-slider-' . wp_rand(1000, 999999);
    $nonce     = wp_create_nonce('gg_ai_slider_design_nonce');
    $ajax_url  = admin_url('admin-ajax.php');

    ob_start();
    ?>

    <section
        id="<?php echo esc_attr($slider_id); ?>"
        class="gg-ai-design-slider"
        aria-label="AI-genererade smyckesidéer"
        data-ajax-url="<?php echo esc_url($ajax_url); ?>"
        data-nonce="<?php echo esc_attr($nonce); ?>"
    >

        <div class="gg-ai-design-slider-head">
            <span>AI-INSPIRATION</span>
            <p>De senaste AI-genererade smyckesidéerna skapade av våra kunder.</p>
        </div>

        <div class="gg-ai-design-slider-track">
            <?php while ($query->have_posts()) : ?>
                <?php
                $query->the_post();

                $source_design_id = get_the_ID();
                $image_url        = get_post_meta($source_design_id, '_gg_design_ai_image_url', true);

                if (!$image_url) {
                    continue;
                }

                if (function_exists('gg_design_is_own_ai_image_url') && !gg_design_is_own_ai_image_url($image_url)) {
                    continue;
                }
                ?>

                <figure class="gg-ai-design-slide">
                    <button
                        type="button"
                        class="gg-ai-design-image-btn"
                        data-source-id="<?php echo esc_attr($source_design_id); ?>"
                        data-image-url="<?php echo esc_attr($image_url); ?>"
                        aria-label="Välj denna AI-genererade smyckesidé"
                    >
                        <img
                            src="<?php echo esc_url($image_url); ?>"
                            alt="AI-genererad smyckesidé från Gold Goblins"
                            width="1024"
                            height="1024"
                            loading="lazy"
                            decoding="async"
                        >
                    </button>

                    <figcaption>Klicka för att välja</figcaption>
                </figure>

            <?php endwhile; ?>
        </div>

        <div class="gg-ai-design-request" hidden>
            <div class="gg-ai-design-request-preview">
                <img src="" alt="Vald AI-genererad smyckesidé" loading="lazy" decoding="async">
            </div>

            <form class="gg-ai-design-request-form">
                <input type="hidden" name="ai_image_url" value="">
                <input type="hidden" name="source_design_id" value="">

                <input
                    type="text"
                    name="website"
                    value=""
                    tabindex="-1"
                    autocomplete="off"
                    class="gg-ai-design-hp"
                    aria-hidden="true"
                >

                <div class="gg-ai-design-request-fields">
                    <label>
                        Namn
                        <input type="text" name="name" required autocomplete="name">
                    </label>

                    <label>
                        E-post
                        <input type="email" name="email" required autocomplete="email">
                    </label>
                </div>

                <label class="gg-ai-design-consent">
                    <input type="checkbox" name="consent" value="1" required>
                    Jag godkänner att Gold Goblins kontaktar mig angående denna designidé.
                </label>

                <button type="submit">SKICKA TILL VERKSTADEN</button>

                <p class="gg-ai-design-request-message" aria-live="polite"></p>
            </form>
        </div>

    </section>

    <style>
  .gg-ai-design-slider{
    position:relative;

    width:100%;
    padding:clamp(22px,3vw,46px) 2%;
    box-sizing:border-box;

    border-top:0;
    
    background-color:#f1dfc4;
    background-image:
        radial-gradient(circle at 20% 15%, rgba(255,255,255,0.10), transparent 30%),
        radial-gradient(circle at 80% 35%, rgba(120,90,55,0.03), transparent 35%),
        radial-gradient(circle at 45% 80%, rgba(255,255,255,0.06), transparent 30%),
        linear-gradient(135deg, rgba(255,255,255,0.03), rgba(120,90,55,0.02));
    background-size:cover;
    background-position:center;
}
	
	.gg-ai-design-slider::before{
    content:"";
    position:absolute;
    left:0;
    right:0;
    top:0;

    height:1px;

    background:linear-gradient(
        90deg,
        transparent 0%,
        rgba(159,133,96,0.28) 18%,
        rgba(159,133,96,0.70) 50%,
        rgba(159,133,96,0.28) 82%,
        transparent 100%
    );

    pointer-events:none;
}

    .gg-ai-design-slider-head{
        width:min(96vw, 1200px);
        margin:0 auto clamp(14px,1.6vw,24px);
        text-align:left;
    }

    .gg-ai-design-slider-head span{
        font-family:'PT Serif', serif;
        color:#B9965F;
        font-size:clamp(13px,1vw,18px);
        letter-spacing:0.22em;
        text-transform:uppercase;
    }

    .gg-ai-design-slider-head p{
        max-width:640px;
        margin:10px 0 0;
        font-family:'PT Serif', serif;
        color:#2f2b25;
        font-size:clamp(13px,0.95vw,16px);
        line-height:1.6;
        letter-spacing:0.05em;
    }

    .gg-ai-design-slider-track{
        width:min(96vw, 1200px);
        margin:0 auto;
        display:grid;
        grid-auto-flow:column;
        grid-auto-columns:calc((100% - 50px) / 6);
        gap:10px;
        overflow-x:auto;
        scroll-snap-type:x mandatory;
        scroll-behavior:smooth;
        scrollbar-width:thin;
        padding-bottom:6px;
    }

    .gg-ai-design-slide{
        margin:0;
        min-width:0;
        scroll-snap-align:start;
        position:relative;
        border:1px solid rgba(159,133,96,0.65);
        background:#ead6b8;
        overflow:hidden;
    }

    .gg-ai-design-image-btn{
        display:block;
        width:100%;
        padding:0;
        border:0;
        background:transparent;
        cursor:pointer;
    }

    .gg-ai-design-image-btn img{
        width:100%;
        height:auto;
        aspect-ratio:1 / 1;
        object-fit:cover;
        display:block;
        transition:opacity 0.2s ease, transform 0.2s ease;
    }

    .gg-ai-design-image-btn:hover img{
        opacity:0.88;
        transform:scale(1.02);
    }

    .gg-ai-design-slide.is-selected{
        border-color:#B9965F;
        box-shadow:0 0 0 2px rgba(185,150,95,0.28);
    }

    .gg-ai-design-slide figcaption{
        position:absolute;
        left:8px;
        bottom:8px;
        padding:4px 7px;
        background:rgba(241,223,196,0.88);
        color:#2f2b25;
        font-family:'PT Serif', serif;
        font-size:10px;
        letter-spacing:0.08em;
        text-transform:uppercase;
        pointer-events:none;
    }

    .gg-ai-design-request{
        width:min(96vw, 1200px);
        margin:clamp(16px,2vw,28px) auto 0;
        padding:clamp(14px,1.8vw,24px);
        box-sizing:border-box;
        border:1px solid rgba(159,133,96,0.65);
        background:rgba(241,223,196,0.65);
        display:grid;
        grid-template-columns:120px 1fr;
        gap:clamp(14px,2vw,26px);
        align-items:start;
    }

    .gg-ai-design-request[hidden]{
        display:none !important;
    }

    .gg-ai-design-request-preview img{
        width:100%;
        aspect-ratio:1 / 1;
        object-fit:cover;
        display:block;
        border:1px solid rgba(159,133,96,0.65);
    }

    .gg-ai-design-request-form{
        width:100%;
    }

    .gg-ai-design-request-fields{
        display:grid;
        grid-template-columns:1fr 1fr;
        gap:12px;
    }

    .gg-ai-design-request-form label{
        display:block;
        font-family:'PT Serif', serif;
        color:#2f2b25;
        font-size:13px;
        letter-spacing:0.08em;
    }

    .gg-ai-design-request-form input[type="text"],
    .gg-ai-design-request-form input[type="email"]{
        width:100%;
        margin-top:6px;
        padding:10px 11px;
        box-sizing:border-box;
        border:1px solid #b8a98f;
        background:#f1dfc4;
        color:#2f2b25;
        font-family:'PT Serif', serif;
        font-size:15px;
    }

    .gg-ai-design-consent{
        display:flex !important;
        align-items:flex-start;
        gap:8px;
        margin:12px 0 14px;
        line-height:1.5;
        letter-spacing:0.04em !important;
    }

    .gg-ai-design-consent input{
        margin-top:3px;
    }

    .gg-ai-design-request-form button{
        display:inline-flex;
        justify-content:center;
        align-items:center;
        padding:10px 18px;
        border:2px solid #aa8a58;
        color:#3a2c1f;
        text-decoration:none;
        font-family:Georgia, "Times New Roman", serif;
        font-size:clamp(12px, 0.8vw, 15px);
        text-transform:uppercase;
        letter-spacing:0.08em;
        cursor:pointer;
        background-color:#f1dfc4;
        transition:all 0.25s ease;
    }

    .gg-ai-design-request-form button:hover{
        transform:translateY(-1px);
        border-color:#c4a26d;
        box-shadow:0 4px 12px rgba(0,0,0,0.08);
    }

    .gg-ai-design-request-form button:disabled{
        opacity:0.65;
        cursor:wait;
    }

    .gg-ai-design-request-message{
        margin:10px 0 0;
        font-family:'PT Serif', serif;
        color:#2f2b25;
        font-size:13px;
        line-height:1.5;
    }

    .gg-ai-design-request-message.is-error{
        color:#8a2e2e;
    }

    .gg-ai-design-hp{
        position:absolute !important;
        left:-9999px !important;
        opacity:0 !important;
    }
	
	.gg-ai-design-request.is-complete{
    display:block;
}

.gg-ai-design-final-message{
    margin:0;
    font-family:'PT Serif', serif;
    color:#2f2b25;
    font-size:clamp(14px,1vw,17px);
    line-height:1.6;
    letter-spacing:0.05em;
}

    @media(max-width:900px){
        .gg-ai-design-slider-track{
            grid-auto-columns:calc((100% - 20px) / 3);
        }

        .gg-ai-design-request{
            grid-template-columns:90px 1fr;
        }
    }

    @media(max-width:600px){
        .gg-ai-design-slider{
            padding:22px 4%;
        }

        .gg-ai-design-slider-track,
        .gg-ai-design-slider-head,
        .gg-ai-design-request{
            width:100%;
        }

        .gg-ai-design-slider-track{
            grid-auto-columns:calc((100% - 10px) / 2);
        }

        .gg-ai-design-request{
            grid-template-columns:1fr;
        }

        .gg-ai-design-request-preview{
            max-width:120px;
        }

        .gg-ai-design-request-fields{
            grid-template-columns:1fr;
        }

        .gg-ai-design-request-form button{
            width:100%;
        }
    }
    </style>

    <script>
    document.addEventListener('DOMContentLoaded', function() {
        const slider = document.getElementById('<?php echo esc_js($slider_id); ?>');

        if (!slider) return;

        const requestBox = slider.querySelector('.gg-ai-design-request');
        const requestForm = slider.querySelector('.gg-ai-design-request-form');
        const previewImg = slider.querySelector('.gg-ai-design-request-preview img');
        const imageInput = slider.querySelector('input[name="ai_image_url"]');
        const sourceIdInput = slider.querySelector('input[name="source_design_id"]');
        const feedback = slider.querySelector('.gg-ai-design-request-message');
        const ajaxUrl = slider.dataset.ajaxUrl;
        const nonce = slider.dataset.nonce;

        slider.querySelectorAll('.gg-ai-design-image-btn').forEach(function(button) {
            button.addEventListener('click', function() {
                const imageUrl = button.dataset.imageUrl;
                const sourceId = button.dataset.sourceId;

                if (!imageUrl || !sourceId || !requestBox || !previewImg || !imageInput || !sourceIdInput) return;

                slider.querySelectorAll('.gg-ai-design-slide').forEach(function(slide) {
                    slide.classList.remove('is-selected');
                });

                button.closest('.gg-ai-design-slide').classList.add('is-selected');

                previewImg.src = imageUrl;
                imageInput.value = imageUrl;
                sourceIdInput.value = sourceId;
                requestBox.hidden = false;

                if (feedback) {
                    feedback.textContent = '';
                    feedback.classList.remove('is-error');
                }

                requestBox.scrollIntoView({
                    behavior: 'smooth',
                    block: 'nearest'
                });
            });
        });

        if (!requestForm) return;

        requestForm.addEventListener('submit', function(e) {
            e.preventDefault();

            const button = requestForm.querySelector('button[type="submit"]');
            const nameInput = requestForm.querySelector('input[name="name"]');
            const emailInput = requestForm.querySelector('input[name="email"]');
            const consentInput = requestForm.querySelector('input[name="consent"]');
            const websiteInput = requestForm.querySelector('input[name="website"]');

            if (!nameInput || !nameInput.checkValidity()) {
                nameInput.reportValidity();
                return;
            }

            if (!emailInput || !emailInput.checkValidity()) {
                emailInput.reportValidity();
                return;
            }

            if (!consentInput || !consentInput.checkValidity()) {
                consentInput.reportValidity();
                return;
            }

            if (!imageInput || !imageInput.value || !sourceIdInput || !sourceIdInput.value) {
                if (feedback) {
                    feedback.textContent = 'Välj en bild först.';
                    feedback.classList.add('is-error');
                }
                return;
            }

            if (feedback) {
                feedback.textContent = '';
                feedback.classList.remove('is-error');
            }

            if (button) {
                button.disabled = true;
                button.textContent = 'SKICKAR…';
            }

            const formData = new FormData();
            formData.append('action', 'gg_ai_slider_design_request');
            formData.append('nonce', nonce);
            formData.append('name', nameInput.value);
            formData.append('email', emailInput.value);
            formData.append('ai_image_url', imageInput.value);
            formData.append('source_design_id', sourceIdInput.value);
            formData.append('consent', consentInput.checked ? '1' : '');
            formData.append('website', websiteInput ? websiteInput.value : '');

            fetch(ajaxUrl, {
                method: 'POST',
                body: formData,
                credentials: 'same-origin'
            })
            .then(function(response) {
                return response.json();
            })
            .then(function(data) {
                if (!data || !data.success) {
                    throw new Error(data && data.data && data.data.message ? data.data.message : 'Något gick fel. Försök igen.');
                }

                const successText = data.data && data.data.message
    ? data.data.message
    : 'Tack! Din förfrågan har skickats till verkstaden.';

const successMessage = document.createElement('p');
successMessage.className = 'gg-ai-design-final-message';
successMessage.textContent = successText;

requestBox.classList.add('is-complete');
requestBox.replaceChildren(successMessage);
            })
            .catch(function(error) {
                if (feedback) {
                    feedback.textContent = error.message;
                    feedback.classList.add('is-error');
                }
            })
            .finally(function() {
                if (button) {
                    button.disabled = false;
                    button.textContent = 'SKICKA TILL VERKSTADEN';
                }
            });
        });
    });
    </script>

    <?php
    wp_reset_postdata();

    return ob_get_clean();
});


add_action('wp_ajax_gg_ai_slider_design_request', 'gg_ai_slider_design_request');
add_action('wp_ajax_nopriv_gg_ai_slider_design_request', 'gg_ai_slider_design_request');

function gg_ai_slider_design_request() {
    if (!check_ajax_referer('gg_ai_slider_design_nonce', 'nonce', false)) {
        wp_send_json_error([
            'message' => 'Säkerhetskontrollen misslyckades. Ladda om sidan och försök igen.'
        ], 403);
    }

    $honeypot = isset($_POST['website']) ? sanitize_text_field(wp_unslash($_POST['website'])) : '';

    if ($honeypot !== '') {
        wp_send_json_success([
            'message' => 'Tack! Din förfrågan har skickats till verkstaden.'
        ]);
    }

    $name             = isset($_POST['name']) ? sanitize_text_field(wp_unslash($_POST['name'])) : '';
    $email            = isset($_POST['email']) ? sanitize_email(wp_unslash($_POST['email'])) : '';
    $source_design_id = isset($_POST['source_design_id']) ? absint($_POST['source_design_id']) : 0;
    $consent          = !empty($_POST['consent']);

    if (!$name || !$email || !$source_design_id) {
        wp_send_json_error([
            'message' => 'Fyll i namn och e-post och välj en bild.'
        ], 400);
    }

    if (!is_email($email)) {
        wp_send_json_error([
            'message' => 'Ange en giltig e-postadress.'
        ], 400);
    }

    if (!$consent) {
        wp_send_json_error([
            'message' => 'Du behöver godkänna att Gold Goblins kontaktar dig angående förfrågan.'
        ], 400);
    }

    $source_post = get_post($source_design_id);

    if (
        !$source_post ||
        $source_post->post_type !== 'gg_customer_design' ||
        $source_post->post_status !== 'publish'
    ) {
        wp_send_json_error([
            'message' => 'Bilden kunde inte verifieras mot en befintlig kunddesign.'
        ], 400);
    }

    $source_type = get_post_meta($source_design_id, '_gg_design_source', true);

    if ($source_type === 'ai_slider_reuse') {
        wp_send_json_error([
            'message' => 'Bilden kunde inte användas som originaldesign.'
        ], 400);
    }

    $ai_image_url = get_post_meta($source_design_id, '_gg_design_ai_image_url', true);
    $ai_image_url = $ai_image_url ? esc_url_raw($ai_image_url) : '';

    if (!$ai_image_url) {
        wp_send_json_error([
            'message' => 'Originalbilden saknar sparad AI-bild.'
        ], 400);
    }

    if (function_exists('gg_design_is_own_ai_image_url') && !gg_design_is_own_ai_image_url($ai_image_url)) {
        wp_send_json_error([
            'message' => 'Originalbilden kunde inte verifieras.'
        ], 400);
    }

    $email_key = function_exists('gg_design_get_email_key')
        ? gg_design_get_email_key($email)
        : hash_hmac('sha256', strtolower(trim($email)), wp_salt('nonce'));

    $rate_key   = 'gg_ai_slider_request_v2_' . $email_key;
    $rate_count = (int) get_transient($rate_key);

    if ($rate_count >= 5) {
        wp_send_json_error([
            'message' => 'För många förfrågningar har skickats från samma e-postadress. Försök igen senare.'
        ], 429);
    }

    if (!function_exists('gg_save_customer_design_request')) {
        wp_send_json_error([
            'message' => 'Kunddesign Hubben är inte tillgänglig just nu.'
        ], 500);
    }

    $ip = isset($_SERVER['REMOTE_ADDR'])
        ? sanitize_text_field(wp_unslash($_SERVER['REMOTE_ADDR']))
        : '';

    $generated_brief  = "Kunden har valt en befintlig AI-genererad inspirationsbild från Gold Goblins AI-inspiration.\n";
    $generated_brief .= "Detta är inte en ny AI-generering, utan en intresseförfrågan baserad på en redan skapad bild.\n\n";
    $generated_brief .= "Vald AI-bild:\n" . $ai_image_url . "\n\n";
    $generated_brief .= "Ursprunglig kunddesign-ID:\n" . $source_design_id . "\n\n";
    $generated_brief .= "Verkstadsnotering:\n";
    $generated_brief .= "Kontakta kunden och bedöm om designen kan tas vidare, justeras eller offereras utifrån material, storlek, konstruktion och budget.";

    $design_request_id = gg_save_customer_design_request([
        'name'            => $name,
        'email'           => $email,
        'phone'           => '',
        'jewelry_type'    => 'AI-inspiration',
        'material'        => 'Ej angivet',
        'style_text'      => 'Vald från AI-slidern',
        'size'            => '',
        'budget'          => '',
        'idea'            => 'Kunden är intresserad av denna AI-genererade inspirationsbild och vill bli kontaktad av verkstaden.',
        'next_step'       => 'Kontakta mig',
        'generated_brief' => $generated_brief,
        'inspiration_url' => '',
        'ai_image_url'    => $ai_image_url,
        'ai_prompt'       => '',
        'customer_ip'     => $ip,
    ]);

    if (!$design_request_id) {
        wp_send_json_error([
            'message' => 'Förfrågan kunde inte sparas. Försök igen eller kontakta oss direkt.'
        ], 500);
    }

    update_post_meta($design_request_id, '_gg_design_source', 'ai_slider_reuse');
    update_post_meta($design_request_id, '_gg_design_source_design_id', $source_design_id);

    set_transient($rate_key, $rate_count + 1, DAY_IN_SECONDS);

    $recipient = apply_filters('gg_design_recipient_email', get_option('admin_email'));

    if ($recipient && is_email($recipient)) {
        $subject = 'Ny förfrågan från AI-inspiration – Gold Goblins';

        $message  = "Ny förfrågan från AI-inspiration\n";
        $message .= "================================\n\n";
        $message .= "Kund\n";
        $message .= "Namn: {$name}\n";
        $message .= "E-post: {$email}\n\n";
        $message .= "Vald AI-bild\n";
        $message .= "--------------------\n";
        $message .= $ai_image_url . "\n\n";
        $message .= "Ursprunglig kunddesign-ID: {$source_design_id}\n\n";
        $message .= "Adminlänk\n";
        $message .= "--------------------\n";
        $message .= admin_url('post.php?post=' . intval($design_request_id) . '&action=edit') . "\n\n";
        $message .= "Obs: Detta är en inspirationsförfrågan från en befintlig AI-bild. Slutlig form, konstruktion och pris behöver bedömas av verkstaden.\n";

        wp_mail($recipient, $subject, $message, [
            'Content-Type: text/plain; charset=UTF-8',
            'Reply-To: ' . $email,
        ]);
    }

    wp_send_json_success([
        'message' => 'Tack! Din förfrågan har skickats till verkstaden.'
    ]);
}

/**
 * Gold Goblins Värdering Hub
 */
if (!defined('ABSPATH')) {
    exit;
}

/**
 * Gold Goblins Värdering Hub
 * Skapar en admin-hubb där varje värderingssektion hanteras som ett eget inlägg.
 */

add_action('init', 'gg_vard_register_content');

function gg_vard_register_content() {

    register_post_type('gg_vard_section', [
        'labels' => [
            'name'                  => 'Värdering Hub',
            'singular_name'         => 'Värderingssektion',
            'menu_name'             => 'Värdering',
            'name_admin_bar'        => 'Värderingssektion',
            'add_new'               => 'Lägg till',
            'add_new_item'          => 'Lägg till sektion',
            'edit_item'             => 'Redigera sektion',
            'new_item'              => 'Ny sektion',
            'view_item'             => 'Visa sektion',
            'search_items'          => 'Sök sektioner',
            'not_found'             => 'Inga sektioner hittades',
            'not_found_in_trash'    => 'Inga sektioner hittades i papperskorgen',
            'all_items'             => 'Alla sektioner',
            'attributes'            => 'Sektionsattribut',
        ],
        'public'              => false,
        'show_ui'             => true,
        'show_in_menu'        => true,
        'menu_icon'           => 'dashicons-clipboard',
        'menu_position'       => 25,
        'supports'            => ['title', 'revisions'],
        'has_archive'         => false,
        'publicly_queryable'  => false,
        'exclude_from_search' => true,
        'show_in_rest'        => false,
    ]);
}

add_filter('use_block_editor_for_post_type', 'gg_vard_disable_block_editor', 10, 2);

function gg_vard_disable_block_editor($use_block_editor, $post_type) {
    if ($post_type === 'gg_vard_section') {
        return false;
    }

    return $use_block_editor;
}

add_action('add_meta_boxes', 'gg_vard_add_meta_boxes');

function gg_vard_add_meta_boxes() {

    add_meta_box(
        'gg_vard_content_box',
        'Värderingssektion',
        'gg_vard_render_content_meta_box',
        'gg_vard_section',
        'normal',
        'high'
    );

    add_meta_box(
        'gg_vard_settings_box',
        'Inställningar',
        'gg_vard_render_settings_meta_box',
        'gg_vard_section',
        'side',
        'default'
    );
}

function gg_vard_render_settings_meta_box($post) {

    wp_nonce_field('gg_vard_save_section', 'gg_vard_nonce');

    $order      = get_post_meta($post->ID, '_gg_vard_order', true);
    $menu_label = get_post_meta($post->ID, '_gg_vard_menu_label', true);

    ?>
    <p>
        <label for="gg_vard_order"><strong>Ordning</strong></label>
        <input
            type="number"
            id="gg_vard_order"
            name="gg_vard_order"
            value="<?php echo esc_attr($order); ?>"
            min="0"
            step="1"
            style="width:100%;"
            placeholder="Exempel: 10"
        >
    </p>

    <p>
        <label for="gg_vard_menu_label"><strong>Menytext</strong></label>
        <input
            type="text"
            id="gg_vard_menu_label"
            name="gg_vard_menu_label"
            value="<?php echo esc_attr($menu_label); ?>"
            style="width:100%;"
            placeholder="Exempel: Översikt"
        >
    </p>

    <p style="color:#646970;font-size:12px;line-height:1.5;">
        Inläggstiteln används internt i admin. Menytexten visas i vänstermenyn på värderingssidan.
    </p>
    <?php
}

function gg_vard_render_content_meta_box($post) {

    $kicker       = get_post_meta($post->ID, '_gg_vard_kicker', true);
    $heading      = get_post_meta($post->ID, '_gg_vard_heading', true);
    $body         = get_post_meta($post->ID, '_gg_vard_body', true);
    $choices      = get_post_meta($post->ID, '_gg_vard_choices', true);
    $price_rows   = get_post_meta($post->ID, '_gg_vard_price_rows', true);
    $button_text  = get_post_meta($post->ID, '_gg_vard_button_text', true);
    $button_url   = get_post_meta($post->ID, '_gg_vard_button_url', true);

    ?>
    <style>
        .gg-vard-admin-wrap{
            display:grid;
            grid-template-columns:minmax(0, 1fr);
            gap:18px;
        }

        .gg-vard-admin-card{
            border:1px solid #d7c4a5;
            background:#fffaf2;
            padding:18px;
        }

        .gg-vard-admin-card h3{
            margin:0 0 14px;
            color:#8a6f45;
            font-family:Georgia, "Times New Roman", serif;
            letter-spacing:.08em;
            text-transform:uppercase;
            font-weight:400;
        }

        .gg-vard-admin-card label{
            display:block;
            margin:0 0 6px;
            color:#8a6f45;
            font-weight:600;
        }

        .gg-vard-admin-card input[type="text"],
        .gg-vard-admin-card input[type="url"],
        .gg-vard-admin-card textarea{
            width:100%;
            box-sizing:border-box;
        }

        .gg-vard-admin-card textarea{
            min-height:90px;
            line-height:1.5;
        }

        .gg-vard-admin-help{
            margin:8px 0 0;
            color:#646970;
            font-size:12px;
            line-height:1.5;
        }
    </style>

    <div class="gg-vard-admin-wrap">

        <div class="gg-vard-admin-card">
            <h3>Rubrik</h3>

            <p>
                <label for="gg_vard_kicker">Kicker</label>
                <input
                    type="text"
                    id="gg_vard_kicker"
                    name="gg_vard_kicker"
                    value="<?php echo esc_attr($kicker); ?>"
                    placeholder="Exempel: Gold Goblins Lidköping"
                >
            </p>

            <p>
                <label for="gg_vard_heading">Huvudrubrik i panelen</label>
                <input
                    type="text"
                    id="gg_vard_heading"
                    name="gg_vard_heading"
                    value="<?php echo esc_attr($heading); ?>"
                    placeholder="Exempel: Värdering av smycken och ädelmetaller"
                >
            </p>
        </div>

        <div class="gg-vard-admin-card">
            <h3>Brödtext</h3>

            <label for="gg_vard_body">Text</label>
            <textarea
                id="gg_vard_body"
                name="gg_vard_body"
                rows="8"
            ><?php echo esc_textarea($body); ?></textarea>

            <p class="gg-vard-admin-help">
                Separera stycken med en tom rad. Enkla HTML-länkar är tillåtna, till exempel:
                &lt;a href="/guld/"&gt;guldpris&lt;/a&gt;
            </p>
        </div>

        <div class="gg-vard-admin-card">
            <h3>Val / informationsrader</h3>

            <label for="gg_vard_choices">Rader</label>
            <textarea
                id="gg_vard_choices"
                name="gg_vard_choices"
                rows="6"
                placeholder="Snabb uppfattning | Muntlig bedömning för dig som vill förstå skick och ungefärligt värde."
            ><?php echo esc_textarea($choices); ?></textarea>

            <p class="gg-vard-admin-help">
                En rad per val. Format: <strong>Titel | Beskrivning</strong>.
                Lämna tomt om sektionen inte ska visa val.
            </p>
        </div>

        <div class="gg-vard-admin-card">
            <h3>Prisrader</h3>

            <label for="gg_vard_price_rows">Priser</label>
            <textarea
                id="gg_vard_price_rows"
                name="gg_vard_price_rows"
                rows="7"
                placeholder="Muntlig smyckesbedömning | 300 kr"
            ><?php echo esc_textarea($price_rows); ?></textarea>

            <p class="gg-vard-admin-help">
                En rad per pris. Format: <strong>Tjänst | Pris</strong>.
                Lämna tomt om sektionen inte ska visa prislista.
            </p>
        </div>

        <div class="gg-vard-admin-card">
            <h3>Knapp</h3>

            <p>
                <label for="gg_vard_button_text">Knapptext</label>
                <input
                    type="text"
                    id="gg_vard_button_text"
                    name="gg_vard_button_text"
                    value="<?php echo esc_attr($button_text); ?>"
                    placeholder="Exempel: Kontakta oss"
                >
            </p>

            <p>
                <label for="gg_vard_button_url">Knapplänk</label>
                <input
                    type="url"
                    id="gg_vard_button_url"
                    name="gg_vard_button_url"
                    value="<?php echo esc_url($button_url); ?>"
                    placeholder="https://www.goldgoblins.se/kontakta-oss/"
                >
            </p>

            <p class="gg-vard-admin-help">
                Lämna knapptext eller länk tom om sektionen inte ska visa knapp.
            </p>
        </div>

    </div>
    <?php
}

add_action('save_post_gg_vard_section', 'gg_vard_save_section_fields');

function gg_vard_save_section_fields($post_id) {

    if (
        !isset($_POST['gg_vard_nonce']) ||
        !wp_verify_nonce(sanitize_text_field(wp_unslash($_POST['gg_vard_nonce'])), 'gg_vard_save_section')
    ) {
        return;
    }

    if (defined('DOING_AUTOSAVE') && DOING_AUTOSAVE) {
        return;
    }

    if (!current_user_can('edit_post', $post_id)) {
        return;
    }

    $order = isset($_POST['gg_vard_order'])
        ? absint($_POST['gg_vard_order'])
        : 0;

    $menu_label = isset($_POST['gg_vard_menu_label'])
        ? sanitize_text_field(wp_unslash($_POST['gg_vard_menu_label']))
        : '';

    $kicker = isset($_POST['gg_vard_kicker'])
        ? sanitize_text_field(wp_unslash($_POST['gg_vard_kicker']))
        : '';

    $heading = isset($_POST['gg_vard_heading'])
        ? sanitize_text_field(wp_unslash($_POST['gg_vard_heading']))
        : '';

    $body = isset($_POST['gg_vard_body'])
        ? wp_kses_post(wp_unslash($_POST['gg_vard_body']))
        : '';

    $choices = isset($_POST['gg_vard_choices'])
        ? sanitize_textarea_field(wp_unslash($_POST['gg_vard_choices']))
        : '';

    $price_rows = isset($_POST['gg_vard_price_rows'])
        ? sanitize_textarea_field(wp_unslash($_POST['gg_vard_price_rows']))
        : '';

    $button_text = isset($_POST['gg_vard_button_text'])
        ? sanitize_text_field(wp_unslash($_POST['gg_vard_button_text']))
        : '';

    $button_url = isset($_POST['gg_vard_button_url'])
        ? esc_url_raw(wp_unslash($_POST['gg_vard_button_url']))
        : '';

    update_post_meta($post_id, '_gg_vard_order', $order);
    update_post_meta($post_id, '_gg_vard_menu_label', $menu_label);
    update_post_meta($post_id, '_gg_vard_kicker', $kicker);
    update_post_meta($post_id, '_gg_vard_heading', $heading);
    update_post_meta($post_id, '_gg_vard_body', $body);
    update_post_meta($post_id, '_gg_vard_choices', $choices);
    update_post_meta($post_id, '_gg_vard_price_rows', $price_rows);
    update_post_meta($post_id, '_gg_vard_button_text', $button_text);
    update_post_meta($post_id, '_gg_vard_button_url', $button_url);
}

function gg_vard_split_paragraphs($text) {
    $text = trim((string) $text);

    if ($text === '') {
        return [];
    }

    $paragraphs = preg_split('/\R{2,}/', $text);
    $clean = [];

    foreach ($paragraphs as $paragraph) {
        $paragraph = trim($paragraph);

        if ($paragraph === '') {
            continue;
        }

        $clean[] = wp_kses_post($paragraph);
    }

    return $clean;
}

function gg_vard_parse_rows($text, $first_key, $second_key) {
    $text = trim((string) $text);

    if ($text === '') {
        return [];
    }

    $lines = preg_split('/\R/', $text);
    $rows = [];

    foreach ($lines as $line) {
        $line = trim($line);

        if ($line === '') {
            continue;
        }

        $parts = array_map('trim', explode('|', $line, 2));

        if (count($parts) < 2 || $parts[0] === '' || $parts[1] === '') {
            continue;
        }

        $rows[] = [
            $first_key  => sanitize_text_field($parts[0]),
            $second_key => sanitize_text_field($parts[1]),
        ];
    }

    return $rows;
}

function gg_vard_get_tabs() {

    $sections = get_posts([
        'post_type'      => 'gg_vard_section',
        'post_status'    => 'publish',
        'posts_per_page' => -1,
        'orderby'        => 'title',
        'order'          => 'ASC',
    ]);

    if (empty($sections)) {
        return [];
    }

    usort($sections, function($a, $b) {
        $a_order = get_post_meta($a->ID, '_gg_vard_order', true);
        $b_order = get_post_meta($b->ID, '_gg_vard_order', true);

        $a_order = $a_order === '' ? 9999 : intval($a_order);
        $b_order = $b_order === '' ? 9999 : intval($b_order);

        if ($a_order === $b_order) {
            return strcasecmp($a->post_title, $b->post_title);
        }

        return $a_order <=> $b_order;
    });

    $tabs = [];

    foreach ($sections as $section) {
        $tab_id = $section->post_name ? sanitize_title($section->post_name) : 'sektion-' . $section->ID;

        if (isset($tabs[$tab_id])) {
            $tab_id .= '-' . $section->ID;
        }

        $menu_label = get_post_meta($section->ID, '_gg_vard_menu_label', true);
        $kicker     = get_post_meta($section->ID, '_gg_vard_kicker', true);
        $heading    = get_post_meta($section->ID, '_gg_vard_heading', true);
        $body       = get_post_meta($section->ID, '_gg_vard_body', true);
        $choices    = get_post_meta($section->ID, '_gg_vard_choices', true);
        $prices     = get_post_meta($section->ID, '_gg_vard_price_rows', true);
        $button_txt = get_post_meta($section->ID, '_gg_vard_button_text', true);
        $button_url = get_post_meta($section->ID, '_gg_vard_button_url', true);

        $tab = [
            'label'  => $menu_label !== '' ? $menu_label : $section->post_title,
            'kicker' => $kicker,
            'title'  => $heading !== '' ? $heading : $section->post_title,
            'body'   => gg_vard_split_paragraphs($body),
        ];

        $parsed_choices = gg_vard_parse_rows($choices, 'title', 'text');

        if (!empty($parsed_choices)) {
            $tab['choices'] = $parsed_choices;
        }

        $parsed_prices = gg_vard_parse_rows($prices, 'service', 'price');

        if (!empty($parsed_prices)) {
            $tab['items'] = $parsed_prices;
        }

        if ($button_txt !== '' && $button_url !== '') {
            $tab['button'] = [
                'text' => $button_txt,
                'url'  => $button_url,
            ];
        }

        $tabs[$tab_id] = $tab;
    }

    return $tabs;
}

add_filter('manage_gg_vard_section_posts_columns', 'gg_vard_admin_columns');

function gg_vard_admin_columns($columns) {

    $new_columns = [];

    foreach ($columns as $key => $label) {
        $new_columns[$key] = $label;

        if ($key === 'title') {
            $new_columns['gg_vard_order'] = 'Ordning';
            $new_columns['gg_vard_menu'] = 'Menytext';
        }
    }

    return $new_columns;
}

add_action('manage_gg_vard_section_posts_custom_column', 'gg_vard_admin_column_content', 10, 2);

function gg_vard_admin_column_content($column, $post_id) {

    if ($column === 'gg_vard_order') {
        $order = get_post_meta($post_id, '_gg_vard_order', true);
        echo $order !== '' ? esc_html($order) : '—';
    }

    if ($column === 'gg_vard_menu') {
        $label = get_post_meta($post_id, '_gg_vard_menu_label', true);
        echo $label !== '' ? esc_html($label) : '—';
    }
}

add_filter('post_updated_messages', 'gg_vard_updated_messages');

function gg_vard_updated_messages($messages) {

    $messages['gg_vard_section'] = [
        0  => '',
        1  => 'Värderingssektionen har uppdaterats.',
        2  => 'Eget fält uppdaterat.',
        3  => 'Eget fält borttaget.',
        4  => 'Värderingssektionen har uppdaterats.',
        5  => 'Värderingssektionen har återställts.',
        6  => 'Värderingssektionen har publicerats.',
        7  => 'Värderingssektionen har sparats.',
        8  => 'Värderingssektionen har skickats.',
        9  => 'Värderingssektionen har schemalagts.',
        10 => 'Utkastet har uppdaterats.',
    ];

    return $messages;
}

/**
 * Gold Goblins Admin Översiktshubb
 */
/**
 * Gold Goblins Admin Översiktshubb
 */

add_action('admin_menu', 'gg_admin_overview_register_menu');

function gg_admin_overview_register_menu() {
    add_menu_page(
        'Gold Goblins Översikt',
        'Översikt',
        'manage_options',
        'gg-admin-overview',
        'gg_admin_overview_render_page',
        'dashicons-chart-area',
        25
    );

    add_submenu_page(
        'gg-admin-overview',
        'Översikt',
        'Översikt',
        'manage_options',
        'gg-admin-overview',
        'gg_admin_overview_render_page'
    );
}


function gg_admin_overview_render_page() {
    if (!current_user_can('manage_options')) {
        wp_die('Du har inte behörighet att visa denna sida.');
    }

    $nonce = wp_create_nonce('gg_admin_overview_stats');
    $ajax_url = admin_url('admin-ajax.php');

    $stats = gg_admin_overview_get_stats();

    $product_interactions = function_exists('gg_activity_get_product_interaction_rows')
        ? gg_activity_get_product_interaction_rows(7, 8)
        : [];
    ?>

    <div class="wrap gg-admin-overview">
        <div class="gg-admin-overview-header">
            <div>
                <h1>Gold Goblins Översikt</h1>
                <p>Samlad intern överblick över kundinteraktioner, ordrar och förfrågningar.</p>
            </div>

            <div class="gg-admin-overview-updated">
                Senast uppdaterad:
                <strong data-gg-stat="updated_at"><?php echo esc_html($stats['updated_at']); ?></strong>
            </div>
        </div>

        <?php gg_admin_overview_render_focus_dashboard($ajax_url, $stats); ?>

        <div class="gg-admin-overview-panel gg-admin-product-interaction-panel">
            <div class="gg-admin-overview-panel-header">
                <h2>Mest interagerade produkter</h2>
                <p>Senaste 7 dagarna</p>
            </div>

            <div class="gg-admin-product-interactions" data-gg-product-interactions>
                <?php echo gg_admin_overview_render_product_interactions($product_interactions); ?>
            </div>
        </div>
    </div>

    <style>
        .gg-admin-overview{
            max-width:1700px;
            margin:0;
        }

        .gg-admin-overview-header{
            display:flex;
            align-items:flex-end;
            justify-content:space-between;
            gap:18px;
            margin:18px 0 14px;
        }

        .gg-admin-overview-header h1{
            margin:0 0 4px;
            color:#2f2b25;
            font-family:Georgia, "Times New Roman", serif;
            font-weight:400;
            font-size:32px;
            line-height:1.05;
        }

        .gg-admin-overview-header p{
            margin:0;
            color:#6b5a43;
            font-size:13px;
            line-height:1.45;
        }

        .gg-admin-overview-updated{
            display:inline-flex;
            align-items:center;
            justify-content:center;
            min-height:34px;
            background:#f1dfc4;
            border:1px solid #c7ab79;
            color:#5f4f39;
            padding:8px 13px;
            font-size:12px;
            white-space:nowrap;
            box-shadow:0 1px 3px rgba(0,0,0,0.04);
        }

        .gg-admin-overview-updated strong{
            color:#2f2b25;
            font-size:13px;
            margin-left:4px;
        }

        .gg-admin-overview-panel{
            background:#fff;
            border:1px solid #ddd3c2;
            padding:0;
            margin-bottom:14px;
            box-shadow:0 1px 5px rgba(0,0,0,0.04);
            overflow:hidden;
        }

        .gg-admin-overview-panel-header{
            display:flex;
            align-items:center;
            justify-content:space-between;
            gap:12px;
            padding:12px 16px;
            border-bottom:1px solid #ddd3c2;
            background:linear-gradient(180deg, #f5e7cd 0%, #f1dfc4 100%);
        }

        .gg-admin-overview-panel-header h2{
            margin:0;
            color:#2f2b25;
            font-family:Georgia, "Times New Roman", serif;
            font-size:18px;
            font-weight:400;
            line-height:1.15;
        }

        .gg-admin-overview-panel-header p{
            margin:0;
            color:#6b5a43;
            font-size:12px;
            line-height:1.35;
            text-align:right;
        }

        .gg-overview-dashboard{
            margin-bottom:14px;
        }

        .gg-overview-dashboard-top{
            display:flex;
            align-items:center;
            justify-content:space-between;
            gap:16px;
            padding:10px 14px;
            background:#fff;
            border-bottom:1px solid #eee7db;
        }

        .gg-overview-periods{
            display:flex;
            align-items:center;
            justify-content:flex-end;
            flex-wrap:wrap;
            gap:6px;
        }

        .gg-overview-periods span{
            margin-right:4px;
            color:#6b5a43;
            font-size:11px;
            text-transform:uppercase;
            letter-spacing:0.08em;
        }

        .gg-overview-periods button{
            border:1px solid #c7ab79;
            background:#f1dfc4;
            color:#2f2b25;
            padding:5px 9px;
            font-size:12px;
            line-height:1.2;
            cursor:pointer;
        }

        .gg-overview-periods button.is-active{
            background:#2f2b25;
            border-color:#2f2b25;
            color:#f1dfc4;
        }

        .gg-overview-kpi-row{
            display:grid;
            grid-template-columns:repeat(4, minmax(0, 1fr));
            gap:10px;
            padding:12px 14px;
            background:#fff;
            border-bottom:1px solid #eee7db;
        }

        .gg-overview-kpi{
            min-height:74px;
            background:linear-gradient(180deg, #f5e7cd 0%, #f1dfc4 100%);
            border:1px solid #c7ab79;
            border-left:4px solid #b9965f;
            padding:10px 12px;
            box-sizing:border-box;
        }

        .gg-overview-kpi span,
        .gg-overview-focus-card span,
        .gg-overview-mini-card span{
            display:block;
            color:#6b5a43;
            font-size:11px;
            text-transform:uppercase;
            letter-spacing:0.08em;
            line-height:1.25;
            margin-bottom:6px;
        }

        .gg-overview-kpi strong,
        .gg-overview-mini-card strong{
            display:block;
            color:#2f2b25;
            font-family:Georgia, "Times New Roman", serif;
            font-size:22px;
            font-weight:400;
            line-height:1.05;
            margin-bottom:4px;
        }

        .gg-overview-kpi small,
        .gg-overview-focus-card small,
        .gg-overview-mini-card small{
            display:block;
            color:#7a6850;
            font-size:12px;
            line-height:1.35;
        }

        .gg-overview-main{
            display:grid;
            grid-template-columns:220px minmax(340px, 1fr) minmax(330px, 0.82fr);
            gap:12px;
            padding:12px 14px;
            background:#fff;
        }

        .gg-overview-focus-card{
            display:flex;
            flex-direction:column;
            justify-content:center;
            min-height:205px;
            background:linear-gradient(180deg, #f5e7cd 0%, #f1dfc4 100%);
            border:1px solid #c7ab79;
            border-left:5px solid #b9965f;
            padding:18px;
            box-sizing:border-box;
        }

        .gg-overview-focus-card strong{
            display:block;
            color:#2f2b25;
            font-family:Georgia, "Times New Roman", serif;
            font-size:34px;
            font-weight:400;
            line-height:1.05;
            margin-bottom:14px;
        }

        .gg-overview-focus-card em{
            display:block;
            margin-top:6px;
            color:#8d7551;
            font-style:normal;
            font-size:12px;
        }

        .gg-overview-chart,
        .gg-overview-donut-panel{
            border:1px solid #eee7db;
            background:#fff;
            min-width:0;
        }

        .gg-overview-chart-head{
            display:flex;
            align-items:center;
            justify-content:space-between;
            gap:10px;
            padding:8px 10px;
            border-bottom:1px solid #eee7db;
            background:#fbf8f3;
        }

        .gg-overview-chart-head strong{
            color:#2f2b25;
            font-family:Georgia, "Times New Roman", serif;
            font-size:15px;
            font-weight:400;
        }

        .gg-overview-chart-head span{
            color:#6b5a43;
            font-size:11px;
            text-align:right;
        }

        .gg-overview-line{
            min-height:180px;
            padding:10px 12px;
            box-sizing:border-box;
            background:
                linear-gradient(180deg, rgba(241,223,196,0.16), rgba(255,255,255,0) 45%),
                #fff;
        }

        .gg-overview-line svg{
            width:100%;
            height:auto;
            display:block;
            overflow:visible;
        }

        .gg-overview-donut-wrap{
            display:grid;
            grid-template-columns:145px minmax(0, 1fr);
            gap:14px;
            align-items:center;
            padding:14px;
            min-height:180px;
            box-sizing:border-box;
        }

        .gg-overview-donut{
            width:138px;
            height:138px;
            border-radius:50%;
            background:#f1dfc4;
            position:relative;
            border:1px solid #c7ab79;
            box-shadow:inset 0 0 0 1px rgba(255,255,255,0.55), 0 2px 8px rgba(0,0,0,0.06);
        }

        .gg-overview-donut::after{
            content:"";
            position:absolute;
            inset:34px;
            border-radius:50%;
            background:#fff;
            border:1px solid #eee7db;
            z-index:1;
        }

        .gg-overview-donut-center{
            position:absolute;
            inset:37px;
            z-index:2;
            display:flex;
            flex-direction:column;
            align-items:center;
            justify-content:center;
            text-align:center;
            color:#2f2b25;
            pointer-events:none;
        }

        .gg-overview-donut-center strong{
            display:block;
            font-family:Georgia, "Times New Roman", serif;
            font-size:22px;
            font-weight:400;
            line-height:1;
        }

        .gg-overview-donut-center span{
            display:block;
            margin-top:4px;
            color:#7a6850;
            font-size:10px;
            text-transform:uppercase;
            letter-spacing:0.07em;
        }

        .gg-overview-legend{
            display:grid;
            gap:7px;
            min-width:0;
        }

        .gg-overview-legend-row{
            display:grid;
            grid-template-columns:11px minmax(0, 1fr) auto;
            gap:7px;
            align-items:center;
            font-size:11px;
            color:#2f2b25;
            min-width:0;
        }

        .gg-overview-legend-dot{
            width:9px;
            height:9px;
            border-radius:50%;
            background:#b9965f;
        }

        .gg-overview-legend-label{
            overflow:hidden;
            text-overflow:ellipsis;
            white-space:nowrap;
            min-width:0;
        }

        .gg-overview-legend-value{
            color:#6b5a43;
            white-space:nowrap;
            font-variant-numeric:tabular-nums;
        }

        .gg-overview-mini-grid{
            display:grid;
            grid-template-columns:repeat(auto-fit, minmax(150px, 1fr));
            gap:8px;
            padding:0 14px 12px;
            background:#fff;
        }

        .gg-overview-mini-card{
            display:block;
            width:100%;
            min-height:72px;
            text-align:left;
            text-decoration:none;
            background:linear-gradient(180deg, #f5e7cd 0%, #f1dfc4 100%);
            border:1px solid #c7ab79;
            border-left:3px solid #b9965f;
            padding:9px 10px;
            box-sizing:border-box;
            color:#2f2b25;
        }

        button.gg-overview-mini-card{
            cursor:pointer;
        }

        button.gg-overview-mini-card:hover{
            border-color:#a78656;
        }

        .gg-overview-mini-card.is-active{
            background:#2f2b25;
            border-color:#2f2b25;
            color:#f1dfc4;
        }

        .gg-overview-mini-card.is-active span{
            color:#d8c39d;
        }

        .gg-overview-mini-card.is-active strong{
            color:#f1dfc4;
        }

        .gg-overview-mini-card.is-active small{
            color:#d8c39d;
        }

        .gg-overview-empty{
            padding:18px;
            color:#7a6850;
            text-align:center;
            font-size:13px;
        }

        .gg-admin-product-interaction-panel{
            margin-bottom:14px;
        }

        .gg-admin-product-interactions table{
            width:100%;
            border-collapse:collapse;
            table-layout:fixed;
        }

        .gg-admin-product-interactions th,
        .gg-admin-product-interactions td{
            padding:9px 14px;
            border-bottom:1px solid #eee7db;
            text-align:left;
            vertical-align:middle;
            word-wrap:break-word;
        }

        .gg-admin-product-interactions th{
            color:#6b5a43;
            font-size:11px;
            text-transform:uppercase;
            letter-spacing:0.08em;
            background:#fbf8f3;
        }

        .gg-admin-product-interactions tbody tr:nth-child(even){
            background:#fcfaf7;
        }

        .gg-admin-product-interactions tbody tr:hover{
            background:#f7f1e7;
        }

        .gg-admin-product-interactions td{
            font-size:13px;
            line-height:1.4;
            color:#2f2b25;
        }

        .gg-admin-product-interactions a{
            color:#9f8560;
            text-decoration:none;
        }

        .gg-admin-product-interactions a:hover{
            text-decoration:underline;
        }

        .gg-admin-product-name{
            display:flex;
            align-items:center;
            gap:10px;
            min-width:0;
        }

        .gg-admin-product-thumb{
            width:38px;
            height:38px;
            min-width:38px;
            object-fit:cover;
            border:1px solid rgba(159,133,96,0.4);
            background:#f1dfc4;
        }

        .gg-admin-product-title{
            display:block;
            color:#9f8560;
            text-decoration:none;
            font-weight:500;
            line-height:1.3;
            margin-bottom:2px;
        }

        .gg-admin-product-links{
            display:flex;
            flex-wrap:wrap;
            gap:8px;
            margin-top:2px;
            font-size:11px;
            line-height:1.3;
        }

        .gg-admin-product-links a{
            color:#7c6a50;
            text-decoration:none;
        }

        .gg-admin-product-links a:hover{
            text-decoration:underline;
        }

        .gg-admin-product-signal{
            display:inline-block;
            padding:3px 7px;
            background:#f1dfc4;
            border:1px solid rgba(159,133,96,0.5);
            color:#2f2b25;
            font-size:11px;
            line-height:1.25;
            white-space:nowrap;
        }

        @media(max-width:1300px){
            .gg-overview-main{
                grid-template-columns:210px minmax(320px, 1fr);
            }

            .gg-overview-donut-panel{
                grid-column:1 / -1;
            }

            .gg-overview-donut-wrap{
                grid-template-columns:145px minmax(0, 1fr);
            }
        }

        @media(max-width:900px){
            .gg-admin-overview-header,
            .gg-admin-overview-panel-header,
            .gg-overview-dashboard-top{
                display:block;
            }

            .gg-admin-overview-updated,
            .gg-overview-periods{
                margin-top:10px;
            }

            .gg-overview-kpi-row{
                grid-template-columns:repeat(2, minmax(0, 1fr));
            }

            .gg-overview-main{
                grid-template-columns:1fr;
            }

            .gg-overview-focus-card{
                min-height:auto;
            }

            .gg-admin-product-interactions table,
            .gg-admin-product-interactions thead,
            .gg-admin-product-interactions tbody,
            .gg-admin-product-interactions th,
            .gg-admin-product-interactions td,
            .gg-admin-product-interactions tr{
                display:block;
            }

            .gg-admin-product-interactions thead{
                display:none;
            }

            .gg-admin-product-interactions tr{
                border-bottom:1px solid #eee7db;
                padding:8px 0;
            }

            .gg-admin-product-interactions td{
                border-bottom:0;
                padding:5px 14px;
            }
        }

        @media(max-width:640px){
            .gg-overview-kpi-row{
                grid-template-columns:1fr;
            }

            .gg-overview-donut-wrap{
                grid-template-columns:1fr;
            }

            .gg-admin-overview-header h1{
                font-size:28px;
            }
        }
    </style>

    <script>
        (function(){
            const ajaxUrl = <?php echo wp_json_encode($ajax_url); ?>;
            const overviewNonce = <?php echo wp_json_encode($nonce); ?>;
            const analyticsNonce = <?php echo wp_json_encode(wp_create_nonce('gg_admin_analytics_nonce')); ?>;

            const dashboard = document.querySelector('[data-gg-overview-dashboard]');

            const state = {
                metric: 'page_views',
                period: 'today'
            };

            const colors = [
                '#b9965f',
                '#2f2b25',
                '#8d7551',
                '#d1b47c',
                '#6b5a43',
                '#c7ab79'
            ];

            const metricMeta = {
                page_views: {
                    title: 'Sidvisningar',
                    description: 'Alla sidladdningar'
                },
                product_views: {
                    title: 'Produktvisningar',
                    description: 'Visade produktsidor'
                },
                add_to_cart: {
                    title: 'Lagt i varukorg',
                    description: 'Produkter tillagda'
                },
                sales: {
                    title: 'Försäljning',
                    description: 'Omsättning'
                }
            };

            function escapeHtml(value){
                const div = document.createElement('div');

                if (value === null || typeof value === 'undefined') {
                    div.textContent = '';
                } else {
                    div.textContent = String(value);
                }

                return div.innerHTML;
            }

            function setFocusStatus(text){
                if (!dashboard) {
                    return;
                }

                const target = dashboard.querySelector('[data-gg-overview-focus-status]');

                if (target) {
                    target.textContent = text;
                }
            }

            function setActiveButtons(){
                if (!dashboard) {
                    return;
                }

                dashboard.querySelectorAll('[data-gg-overview-metric]').forEach(function(button){
                    button.classList.toggle('is-active', button.dataset.ggOverviewMetric === state.metric);
                });

                dashboard.querySelectorAll('[data-gg-overview-period]').forEach(function(button){
                    button.classList.toggle('is-active', button.dataset.ggOverviewPeriod === state.period);
                });
            }

            function loadFocusAnalytics(){
                if (!dashboard) {
                    return;
                }

                setActiveButtons();
                setFocusStatus('Laddar...');

                const formData = new FormData();

                formData.append('action', 'gg_admin_analytics_get_data');
                formData.append('nonce', analyticsNonce);
                formData.append('metric', state.metric);
                formData.append('period', state.period);

                fetch(ajaxUrl, {
                    method: 'POST',
                    credentials: 'same-origin',
                    body: formData
                })
                .then(function(response){
                    return response.json();
                })
                .then(function(response){
                    if (!response || !response.success || !response.data) {
                        setFocusStatus('Kunde inte hämta statistik.');
                        return;
                    }

                    renderFocusDashboard(response.data);
                    setFocusStatus('Uppdaterad: ' + response.data.generated_at);
                })
                .catch(function(){
                    setFocusStatus('Kunde inte hämta statistik.');
                });
            }

            function renderFocusDashboard(data){
                renderSummaryKpis(data.kpis || []);

                const meta = metricMeta[state.metric] || metricMeta.page_views;
                const mainKpi = data.kpis && data.kpis.length ? data.kpis[0] : {
                    label: meta.title,
                    value: '0',
                    description: meta.description
                };

                const periodLabel = data.period_label || '';
                const focusTitle = dashboard.querySelector('[data-gg-overview-focus-title]');
                const focusValue = dashboard.querySelector('[data-gg-overview-focus-value]');
                const focusDescription = dashboard.querySelector('[data-gg-overview-focus-description]');
                const focusTotal = dashboard.querySelector('[data-gg-overview-focus-total]');
                const lineTitle = dashboard.querySelector('[data-gg-overview-line-title]');
                const lineSubtitle = dashboard.querySelector('[data-gg-overview-line-subtitle]');
                const donutTitle = dashboard.querySelector('[data-gg-overview-donut-title]');
                const donutSubtitle = dashboard.querySelector('[data-gg-overview-donut-subtitle]');

                if (focusTitle) {
                    focusTitle.textContent = meta.title + (periodLabel ? ': ' + periodLabel : '');
                }

                if (focusValue) {
                    focusValue.innerHTML = escapeHtml(mainKpi.value);
                }

                if (focusDescription) {
                    focusDescription.textContent = meta.description;
                }

                if (focusTotal) {
                    focusTotal.textContent = 'Totalt: ' + mainKpi.value;
                }

                if (lineTitle) {
                    lineTitle.textContent = data.line_title || 'Utveckling över tid';
                }

                if (lineSubtitle) {
                    lineSubtitle.textContent = periodLabel;
                }

                if (donutTitle) {
                    donutTitle.textContent = data.donut_title || 'Fördelning';
                }

                if (donutSubtitle) {
                    donutSubtitle.textContent = data.donut_subtitle || '';
                }

                renderLineChart(data.series || []);
                renderDonut(data.segments || []);
            }

            function renderSummaryKpis(kpis){
                const target = dashboard.querySelector('[data-gg-overview-kpis]');

                if (!target) {
                    return;
                }

                if (!kpis.length) {
                    target.innerHTML = '<div class="gg-overview-empty">Ingen sammanfattning att visa.</div>';
                    return;
                }

                target.innerHTML = kpis.map(function(kpi){
                    return ''
                        + '<div class="gg-overview-kpi">'
                        + '<span>' + escapeHtml(kpi.label) + '</span>'
                        + '<strong>' + escapeHtml(kpi.value) + '</strong>'
                        + '<small>' + escapeHtml(kpi.description || '') + '</small>'
                        + '</div>';
                }).join('');
            }

            function renderLineChart(series){
                const target = dashboard.querySelector('[data-gg-overview-line]');

                if (!target) {
                    return;
                }

                if (!series || !series.length) {
                    target.innerHTML = '<div class="gg-overview-empty">Ingen data för vald period.</div>';
                    return;
                }

                const width = 620;
                const height = 190;
                const paddingLeft = 38;
                const paddingRight = 14;
                const paddingTop = 20;
                const paddingBottom = 32;

                const chartWidth = width - paddingLeft - paddingRight;
                const chartHeight = height - paddingTop - paddingBottom;

                let maxValue = 1;

                series.forEach(function(point){
                    const value = Number(point.value) || 0;

                    if (value > maxValue) {
                        maxValue = value;
                    }
                });

                const niceMax = Math.max(1, Math.ceil(maxValue));

                const points = series.map(function(point, index){
                    const value = Number(point.value) || 0;
                    const x = paddingLeft + (
                        series.length === 1
                            ? chartWidth / 2
                            : (index / (series.length - 1)) * chartWidth
                    );

                    const y = paddingTop + chartHeight - (value / niceMax) * chartHeight;

                    return {
                        x: x,
                        y: y,
                        label: point.label,
                        value: value
                    };
                });

                const path = points.map(function(point, index){
                    return (index === 0 ? 'M' : 'L') + point.x.toFixed(2) + ' ' + point.y.toFixed(2);
                }).join(' ');

                const firstPoint = points[0];
                const lastPoint = points[points.length - 1];

                const areaPath = path +
                    ' L ' + lastPoint.x.toFixed(2) + ' ' + (height - paddingBottom) +
                    ' L ' + firstPoint.x.toFixed(2) + ' ' + (height - paddingBottom) +
                    ' Z';

                const labelIndexes = [];

                if (points.length <= 8) {
                    points.forEach(function(point, index){
                        labelIndexes.push(index);
                    });
                } else {
                    labelIndexes.push(0);
                    labelIndexes.push(Math.floor((points.length - 1) / 2));
                    labelIndexes.push(points.length - 1);
                }

                const horizontalGrid = [0, 0.5, 1].map(function(step){
                    const y = paddingTop + chartHeight - (step * chartHeight);
                    const value = Math.round(niceMax * step);

                    return ''
                        + '<line x1="' + paddingLeft + '" y1="' + y + '" x2="' + (width - paddingRight) + '" y2="' + y + '" stroke="#eee7db" stroke-width="1" />'
                        + '<text x="' + (paddingLeft - 8) + '" y="' + (y + 4) + '" fill="#7a6850" font-size="10" text-anchor="end">' + escapeHtml(value) + '</text>';
                }).join('');

                const circles = points.map(function(point){
                    const active = point.value > 0;
                    const radius = active ? '4.2' : '2.6';
                    const color = active ? '#2f2b25' : '#8d7551';

                    return ''
                        + '<circle cx="' + point.x + '" cy="' + point.y + '" r="' + radius + '" fill="' + color + '">'
                        + '<title>' + escapeHtml(point.label) + ': ' + escapeHtml(point.value) + '</title>'
                        + '</circle>';
                }).join('');

                const labels = labelIndexes.map(function(index){
                    const point = points[index];
                    const anchor = index === 0 ? 'start' : (index === points.length - 1 ? 'end' : 'middle');

                    return ''
                        + '<text x="' + point.x + '" y="' + (height - 10) + '" fill="#6b5a43" font-size="10" text-anchor="' + anchor + '">'
                        + escapeHtml(point.label)
                        + '</text>';
                }).join('');

                target.innerHTML = ''
                    + '<svg viewBox="0 0 ' + width + ' ' + height + '" role="img" aria-label="Linjediagram">'
                    + '<defs>'
                    + '<linearGradient id="ggOverviewLineGradient" x1="0" x2="0" y1="0" y2="1">'
                    + '<stop offset="0%" stop-color="#1fa84f" stop-opacity="0.22" />'
                    + '<stop offset="100%" stop-color="#1fa84f" stop-opacity="0" />'
                    + '</linearGradient>'
                    + '</defs>'
                    + horizontalGrid
                    + '<line x1="' + paddingLeft + '" y1="' + paddingTop + '" x2="' + paddingLeft + '" y2="' + (height - paddingBottom) + '" stroke="#ddd3c2" stroke-width="1" />'
                    + '<line x1="' + paddingLeft + '" y1="' + (height - paddingBottom) + '" x2="' + (width - paddingRight) + '" y2="' + (height - paddingBottom) + '" stroke="#ddd3c2" stroke-width="1" />'
                    + '<path d="' + areaPath + '" fill="url(#ggOverviewLineGradient)" />'
                    + '<path d="' + path + '" fill="none" stroke="#1fa84f" stroke-width="4" stroke-linecap="round" stroke-linejoin="round" />'
                    + circles
                    + labels
                    + '</svg>';
            }

            function renderDonut(segments){
                const donut = dashboard.querySelector('[data-gg-overview-donut]');
                const legend = dashboard.querySelector('[data-gg-overview-legend]');

                if (!donut || !legend) {
                    return;
                }

                if (!segments || !segments.length) {
                    donut.style.background = '#f1dfc4';
                    donut.innerHTML = '<div class="gg-overview-donut-center"><strong>0</strong><span>Totalt</span></div>';
                    legend.innerHTML = '<div class="gg-overview-empty">Ingen fördelning att visa.</div>';
                    return;
                }

                const total = segments.reduce(function(sum, segment){
                    return sum + (Number(segment.value) || 0);
                }, 0);

                if (!total) {
                    donut.style.background = '#f1dfc4';
                    donut.innerHTML = '<div class="gg-overview-donut-center"><strong>0</strong><span>Totalt</span></div>';
                    legend.innerHTML = '<div class="gg-overview-empty">Ingen fördelning att visa.</div>';
                    return;
                }

                let start = 0;

                const gradient = segments.map(function(segment, index){
                    const value = Number(segment.value) || 0;
                    const percent = value / total * 100;
                    const end = start + percent;
                    const color = colors[index % colors.length];
                    const part = color + ' ' + start.toFixed(2) + '% ' + end.toFixed(2) + '%';

                    start = end;

                    return part;
                }).join(', ');

                donut.style.background = 'conic-gradient(' + gradient + ')';
                donut.innerHTML = ''
                    + '<div class="gg-overview-donut-center">'
                    + '<strong>' + escapeHtml(total) + '</strong>'
                    + '<span>Totalt</span>'
                    + '</div>';

                legend.innerHTML = segments.map(function(segment, index){
                    const value = Number(segment.value) || 0;
                    const percent = total ? Math.round(value / total * 100) : 0;
                    const color = colors[index % colors.length];

                    return ''
                        + '<div class="gg-overview-legend-row">'
                        + '<span class="gg-overview-legend-dot" style="background:' + color + '"></span>'
                        + '<span class="gg-overview-legend-label" title="' + escapeHtml(segment.label) + '">' + escapeHtml(segment.label) + '</span>'
                        + '<span class="gg-overview-legend-value">' + escapeHtml(value) + ' · ' + escapeHtml(percent) + '%</span>'
                        + '</div>';
                }).join('');
            }

            function updateOverview(){
                const formData = new FormData();

                formData.append('action', 'gg_admin_overview_get_stats');
                formData.append('nonce', overviewNonce);

                fetch(ajaxUrl, {
                    method: 'POST',
                    credentials: 'same-origin',
                    body: formData
                })
                .then(function(response){
                    return response.json();
                })
                .then(function(data){
                    if (!data || !data.success || !data.data) {
                        return;
                    }

                    if (data.data.stats) {
                        Object.keys(data.data.stats).forEach(function(key){
                            document.querySelectorAll('[data-gg-stat="' + key + '"]').forEach(function(target){
                                target.innerHTML = data.data.stats[key];
                            });
                        });
                    }

                    if (data.data.product_interaction_html) {
                        const productInteractions = document.querySelector('[data-gg-product-interactions]');

                        if (productInteractions) {
                            productInteractions.innerHTML = data.data.product_interaction_html;
                        }
                    }

                    loadFocusAnalytics();
                })
                .catch(function(){
                    // Tyst fail. Hubben uppdateras igen vid nästa intervall.
                });
            }

            if (dashboard) {
                dashboard.addEventListener('click', function(e){
                    const metricButton = e.target.closest('[data-gg-overview-metric]');
                    const periodButton = e.target.closest('[data-gg-overview-period]');

                    if (metricButton) {
                        state.metric = metricButton.dataset.ggOverviewMetric;
                        loadFocusAnalytics();
                    }

                    if (periodButton) {
                        state.period = periodButton.dataset.ggOverviewPeriod;
                        loadFocusAnalytics();
                    }
                });

                loadFocusAnalytics();
            }

            setInterval(updateOverview, 45000);
        })();
    </script>

    <?php
}


function gg_admin_overview_render_focus_dashboard($ajax_url, $stats) {
    ?>
    <div class="gg-admin-overview-panel gg-overview-dashboard" data-gg-overview-dashboard>
        <div class="gg-admin-overview-panel-header">
            <h2>Översikt</h2>

            <div class="gg-overview-periods">
                <span>Period</span>
                <button type="button" class="is-active" data-gg-overview-period="today">Idag</button>
                <button type="button" data-gg-overview-period="7days">7 dagar</button>
                <button type="button" data-gg-overview-period="30days">30 dagar</button>
                <button type="button" data-gg-overview-period="quarter">Kvartal</button>
                <button type="button" data-gg-overview-period="total">Totalt</button>
            </div>
        </div>

        <div class="gg-overview-kpi-row" data-gg-overview-kpis>
            <div class="gg-overview-kpi">
                <span>Sidvisningar</span>
                <strong><?php echo esc_html($stats['activity_page_views_today']); ?></strong>
                <small>Idag</small>
            </div>

            <div class="gg-overview-kpi">
                <span>Unika sessioner</span>
                <strong><?php echo esc_html($stats['activity_unique_sessions_today']); ?></strong>
                <small>Från färsk aktivitetslogg</small>
            </div>

            <div class="gg-overview-kpi">
                <span>Största post</span>
                <strong>—</strong>
                <small>Laddar statistik...</small>
            </div>

            <div class="gg-overview-kpi">
                <span>Senaste aktivitet</span>
                <strong>—</strong>
                <small>Laddar statistik...</small>
            </div>
        </div>

        <div class="gg-overview-main">
            <div class="gg-overview-focus-card">
                <span data-gg-overview-focus-title>Sidvisningar: Idag</span>
                <strong data-gg-overview-focus-value><?php echo esc_html($stats['activity_page_views_today']); ?></strong>
                <small data-gg-overview-focus-description>Alla sidladdningar</small>
                <em data-gg-overview-focus-total>Totalt: <?php echo esc_html($stats['activity_page_views_total']); ?></em>
            </div>

            <div class="gg-overview-chart">
                <div class="gg-overview-chart-head">
                    <strong data-gg-overview-line-title>Sidvisningar över tid</strong>
                    <span data-gg-overview-focus-status>Laddar statistik...</span>
                </div>

                <div class="gg-overview-line" data-gg-overview-line></div>
            </div>

            <div class="gg-overview-donut-panel">
                <div class="gg-overview-chart-head">
                    <strong data-gg-overview-donut-title>Toppsidor</strong>
                    <span data-gg-overview-donut-subtitle></span>
                </div>

                <div class="gg-overview-donut-wrap">
                    <div class="gg-overview-donut" data-gg-overview-donut></div>
                    <div class="gg-overview-legend" data-gg-overview-legend></div>
                </div>
            </div>
        </div>

        <div class="gg-overview-mini-grid">
            <button type="button" class="gg-overview-mini-card is-active" data-gg-overview-metric="page_views">
                <span>Sidvisningar idag</span>
                <strong data-gg-stat="activity_page_views_today"><?php echo esc_html($stats['activity_page_views_today']); ?></strong>
                <small>Alla sidladdningar<br>Totalt: <b data-gg-stat="activity_page_views_total"><?php echo esc_html($stats['activity_page_views_total']); ?></b></small>
            </button>

            <button type="button" class="gg-overview-mini-card" data-gg-overview-metric="sales">
                <span>Omsättning idag</span>
                <strong data-gg-stat="revenue_today"><?php echo wp_kses_post($stats['revenue_today']); ?></strong>
                <small>Betalda / behandlade ordrar</small>
            </button>

            <div class="gg-overview-mini-card">
                <span>Ordrar idag</span>
                <strong data-gg-stat="orders_today"><?php echo esc_html($stats['orders_today']); ?></strong>
                <small>WooCommerce</small>
            </div>

            <a class="gg-overview-mini-card" href="<?php echo esc_url(admin_url('admin.php?page=wc-orders')); ?>">
                <span>Aktiva ordrar</span>
                <strong data-gg-stat="orders_active"><?php echo esc_html($stats['orders_active']); ?></strong>
                <small>Väntar / behandlas</small>
            </a>

            <a class="gg-overview-mini-card" href="<?php echo esc_url(admin_url('edit.php?post_type=gg_customer_design')); ?>">
                <span>Nya kunddesigner</span>
                <strong data-gg-stat="designs_new"><?php echo esc_html($stats['designs_new']); ?></strong>
                <small>Status: Ny</small>
            </a>

            <a class="gg-overview-mini-card" href="<?php echo esc_url(admin_url('edit.php?post_type=gg_customer_design')); ?>">
                <span>Pågående designer</span>
                <strong data-gg-stat="designs_active"><?php echo esc_html($stats['designs_active']); ?></strong>
                <small>Kontaktad / offert / pågående</small>
            </a>

            <a class="gg-overview-mini-card" href="<?php echo esc_url(admin_url('edit.php?post_type=gg_contact_message')); ?>">
                <span>Kontakt idag</span>
                <strong data-gg-stat="contacts_today"><?php echo esc_html($stats['contacts_today']); ?></strong>
                <small>Nya meddelanden idag</small>
            </a>

            <a class="gg-overview-mini-card" href="<?php echo esc_url(admin_url('edit.php?post_type=gg_contact_message')); ?>">
                <span>Kontakt totalt</span>
                <strong data-gg-stat="contacts_total"><?php echo esc_html($stats['contacts_total']); ?></strong>
                <small>Sparade kontaktärenden</small>
            </a>

            <button type="button" class="gg-overview-mini-card" data-gg-overview-metric="product_views">
                <span>Produktvisningar idag</span>
                <strong data-gg-stat="activity_product_views_today"><?php echo esc_html($stats['activity_product_views_today']); ?></strong>
                <small>Visade produktsidor<br>Totalt: <b data-gg-stat="activity_product_views_total"><?php echo esc_html($stats['activity_product_views_total']); ?></b></small>
            </button>

            <button type="button" class="gg-overview-mini-card" data-gg-overview-metric="add_to_cart">
                <span>Lagt i varukorg idag</span>
                <strong data-gg-stat="activity_add_to_cart_today"><?php echo esc_html($stats['activity_add_to_cart_today']); ?></strong>
                <small>Produkter tillagda<br>Totalt: <b data-gg-stat="activity_add_to_cart_total"><?php echo esc_html($stats['activity_add_to_cart_total']); ?></b></small>
            </button>

            <div class="gg-overview-mini-card">
                <span>Varukorg öppnad idag</span>
                <strong data-gg-stat="activity_cart_open_today"><?php echo esc_html($stats['activity_cart_open_today']); ?></strong>
                <small>Klick på varukorg<br>Totalt: <b data-gg-stat="activity_cart_open_total"><?php echo esc_html($stats['activity_cart_open_total']); ?></b></small>
            </div>

            <div class="gg-overview-mini-card">
                <span>Produktbild klickad idag</span>
                <strong data-gg-stat="activity_gallery_clicks_today"><?php echo esc_html($stats['activity_gallery_clicks_today']); ?></strong>
                <small>Bildinteraktioner<br>Totalt: <b data-gg-stat="activity_gallery_clicks_total"><?php echo esc_html($stats['activity_gallery_clicks_total']); ?></b></small>
            </div>

            <div class="gg-overview-mini-card">
                <span>Paneler öppnade idag</span>
                <strong data-gg-stat="activity_panel_opens_today"><?php echo esc_html($stats['activity_panel_opens_today']); ?></strong>
                <small>Storleksguide / info<br>Totalt: <b data-gg-stat="activity_panel_opens_total"><?php echo esc_html($stats['activity_panel_opens_total']); ?></b></small>
            </div>

            <div class="gg-overview-mini-card">
                <span>Formulärstarter idag</span>
                <strong data-gg-stat="activity_form_starts_today"><?php echo esc_html($stats['activity_form_starts_today']); ?></strong>
                <small>Kontakt / kunddesign<br>Totalt: <b data-gg-stat="activity_form_starts_total"><?php echo esc_html($stats['activity_form_starts_total']); ?></b></small>
            </div>

            <div class="gg-overview-mini-card">
                <span>Formulär skickade idag</span>
                <strong data-gg-stat="activity_form_submits_today"><?php echo esc_html($stats['activity_form_submits_today']); ?></strong>
                <small>Kontakt / kunddesign<br>Totalt: <b data-gg-stat="activity_form_submits_total"><?php echo esc_html($stats['activity_form_submits_total']); ?></b></small>
            </div>

            <div class="gg-overview-mini-card">
                <span>Aktiva sessioner idag</span>
                <strong data-gg-stat="activity_unique_sessions_today"><?php echo esc_html($stats['activity_unique_sessions_today']); ?></strong>
                <small>Unika aktivitets-sessioner<br>Totalt: <b data-gg-stat="activity_unique_sessions_total"><?php echo esc_html($stats['activity_unique_sessions_total']); ?></b></small>
            </div>
        </div>
    </div>
    <?php
}

add_action('wp_ajax_gg_admin_overview_get_stats', 'gg_admin_overview_ajax_get_stats');

function gg_admin_overview_ajax_get_stats() {
    if (!current_user_can('manage_options')) {
        wp_send_json_error([
            'message' => 'Du har inte behörighet att visa denna statistik.',
        ], 403);
    }

    if (
        empty($_POST['nonce']) ||
        !wp_verify_nonce(sanitize_text_field(wp_unslash($_POST['nonce'])), 'gg_admin_overview_stats')
    ) {
        wp_send_json_error([
            'message' => 'Säkerhetskontrollen misslyckades.',
        ], 403);
    }

    $product_interactions = function_exists('gg_activity_get_product_interaction_rows')
        ? gg_activity_get_product_interaction_rows(7, 8)
        : [];

    wp_send_json_success([
        'stats'                    => gg_admin_overview_get_stats(),
        'product_interaction_html' => gg_admin_overview_render_product_interactions($product_interactions),
    ]);
}


function gg_admin_overview_get_stats() {
    $today_start_mysql = date_i18n('Y-m-d 00:00:00', current_time('timestamp'));

    $stats = [
        'orders_today'                    => 0,
        'orders_active'                   => 0,
        'revenue_today'                   => '0 kr',
        'revenue_7_days'                  => '0 kr',
        'designs_new'                     => 0,
        'designs_active'                  => 0,
        'contacts_today'                  => 0,
        'contacts_total'                  => 0,

        'activity_page_views_today'       => 0,
        'activity_page_views_total'       => 0,
        'activity_product_views_today'    => 0,
        'activity_product_views_total'    => 0,
        'activity_add_to_cart_today'      => 0,
        'activity_add_to_cart_total'      => 0,
        'activity_cart_open_today'        => 0,
        'activity_cart_open_total'        => 0,
        'activity_gallery_clicks_today'   => 0,
        'activity_gallery_clicks_total'   => 0,
        'activity_panel_opens_today'      => 0,
        'activity_panel_opens_total'      => 0,
        'activity_form_starts_today'      => 0,
        'activity_form_starts_total'      => 0,
        'activity_form_submits_today'     => 0,
        'activity_form_submits_total'     => 0,
        'activity_unique_sessions_today'  => 0,
        'activity_unique_sessions_total'  => 0,

        'updated_at'                      => date_i18n('Y-m-d H:i:s', current_time('timestamp')),
    ];

    if (post_type_exists('gg_customer_design')) {
        $stats['designs_new'] = gg_admin_overview_count_posts([
            'post_type'   => 'gg_customer_design',
            'post_status' => 'publish',
            'meta_query'  => [
                [
                    'key'   => '_gg_design_status',
                    'value' => 'Ny',
                ],
            ],
        ]);

        $stats['designs_active'] = gg_admin_overview_count_posts([
            'post_type'   => 'gg_customer_design',
            'post_status' => 'publish',
            'meta_query'  => [
                [
                    'key'     => '_gg_design_status',
                    'value'   => ['Kontaktad', 'Offert skickad', 'Pågående'],
                    'compare' => 'IN',
                ],
            ],
        ]);
    }

    if (post_type_exists('gg_contact_message')) {
        $stats['contacts_today'] = gg_admin_overview_count_posts([
            'post_type'   => 'gg_contact_message',
            'post_status' => 'private',
            'date_query'  => [
                [
                    'after'     => $today_start_mysql,
                    'inclusive' => true,
                ],
            ],
        ]);

        $stats['contacts_total'] = gg_admin_overview_count_posts([
            'post_type'   => 'gg_contact_message',
            'post_status' => 'private',
        ]);
    }

    if (class_exists('WooCommerce') && function_exists('wc_get_orders')) {
        $today_start = strtotime(date_i18n('Y-m-d 00:00:00', current_time('timestamp')));
        $week_start  = strtotime('-7 days', current_time('timestamp'));

        $orders_today = wc_get_orders([
            'limit'        => -1,
            'status'       => ['processing', 'completed'],
            'return'       => 'objects',
            'date_created' => '>=' . $today_start,
        ]);

        $orders_week = wc_get_orders([
            'limit'        => -1,
            'status'       => ['processing', 'completed'],
            'return'       => 'objects',
            'date_created' => '>=' . $week_start,
        ]);

        $active_orders = wc_get_orders([
            'limit'  => -1,
            'status' => ['pending', 'on-hold', 'processing'],
            'return' => 'ids',
        ]);

        $today_total = 0;
        $week_total  = 0;

        foreach ($orders_today as $order) {
            $today_total += (float) $order->get_total();
        }

        foreach ($orders_week as $order) {
            $week_total += (float) $order->get_total();
        }

        $stats['orders_today']   = count($orders_today);
        $stats['orders_active']  = count($active_orders);
        $stats['revenue_today']  = wc_price($today_total);
        $stats['revenue_7_days'] = wc_price($week_total);
    }

    if (function_exists('gg_activity_count_events')) {
        $stats['activity_page_views_today'] = gg_activity_count_events('page_view', $today_start_mysql);

        $stats['activity_product_views_today'] = gg_activity_count_events('product_view', $today_start_mysql);

        $stats['activity_add_to_cart_today'] = gg_activity_count_events('add_to_cart', $today_start_mysql);

        $stats['activity_cart_open_today'] = gg_activity_count_events('cart_open', $today_start_mysql);

        $stats['activity_gallery_clicks_today'] = gg_activity_count_events('product_gallery_click', $today_start_mysql);

        $stats['activity_panel_opens_today'] = gg_activity_count_events('info_panel_open', $today_start_mysql);

        $stats['activity_form_starts_today'] = gg_activity_count_events(
            ['contact_form_start', 'design_form_start'],
            $today_start_mysql
        );

        $stats['activity_form_submits_today'] = gg_activity_count_events(
            ['contact_form_submit', 'design_form_submit'],
            $today_start_mysql
        );
    }

    if (function_exists('gg_activity_total_get')) {
        $stats['activity_page_views_total'] = gg_activity_total_get('page_view');

        $stats['activity_product_views_total'] = gg_activity_total_get('product_view');

        $stats['activity_add_to_cart_total'] = gg_activity_total_get('add_to_cart');

        $stats['activity_cart_open_total'] = gg_activity_total_get('cart_open');

        $stats['activity_gallery_clicks_total'] = gg_activity_total_get('product_gallery_click');

        $stats['activity_panel_opens_total'] = gg_activity_total_get('info_panel_open');

        $stats['activity_form_starts_total'] = gg_activity_total_get([
            'contact_form_start',
            'design_form_start',
        ]);

        $stats['activity_form_submits_total'] = gg_activity_total_get([
            'contact_form_submit',
            'design_form_submit',
        ]);
    }

    if (function_exists('gg_activity_count_unique_sessions')) {
        $stats['activity_unique_sessions_today'] = gg_activity_count_unique_sessions($today_start_mysql);
    }

    if (function_exists('gg_activity_total_get_unique_sessions')) {
        $stats['activity_unique_sessions_total'] = gg_activity_total_get_unique_sessions();
    }

    return $stats;
}


function gg_admin_overview_count_posts($args) {
    $query = new WP_Query(array_merge([
        'posts_per_page' => 1,
        'fields'         => 'ids',
        'no_found_rows'  => false,
    ], $args));

    return (int) $query->found_posts;
}


function gg_admin_overview_render_product_interactions($products) {
    ob_start();
    ?>

    <table>
        <thead>
            <tr>
                <th>Produkt</th>
                <th>Visningar</th>
                <th>Varukorg</th>
                <th>Bildklick</th>
                <th>Paneler</th>
                <th>Signal</th>
            </tr>
        </thead>

        <tbody>
            <?php if (!empty($products)) : ?>
                <?php foreach ($products as $product) : ?>
                    <tr>
                        <td>
                            <div class="gg-admin-product-name">
                                <?php
                                if (!empty($product['image_id'])) {
                                    echo wp_get_attachment_image($product['image_id'], 'thumbnail', false, [
                                        'class'    => 'gg-admin-product-thumb',
                                        'loading'  => 'lazy',
                                        'decoding' => 'async',
                                    ]);
                                } else {
                                    echo '<span class="gg-admin-product-thumb"></span>';
                                }
                                ?>

                                <div>
                                    <?php if (!empty($product['edit_link'])) : ?>
                                        <a class="gg-admin-product-title" href="<?php echo esc_url($product['edit_link']); ?>">
                                            <?php echo esc_html($product['product_name']); ?>
                                        </a>
                                    <?php else : ?>
                                        <span class="gg-admin-product-title">
                                            <?php echo esc_html($product['product_name']); ?>
                                        </span>
                                    <?php endif; ?>

                                    <div class="gg-admin-product-links">
                                        <?php if (!empty($product['edit_link'])) : ?>
                                            <a href="<?php echo esc_url($product['edit_link']); ?>">Redigera</a>
                                        <?php endif; ?>

                                        <?php if (!empty($product['permalink'])) : ?>
                                            <a href="<?php echo esc_url($product['permalink']); ?>" target="_blank" rel="noopener noreferrer">Öppna</a>
                                        <?php endif; ?>
                                    </div>
                                </div>
                            </div>
                        </td>

                        <td><?php echo esc_html($product['product_views']); ?></td>
                        <td><?php echo esc_html($product['add_to_cart']); ?></td>
                        <td><?php echo esc_html($product['gallery_clicks']); ?></td>
                        <td><?php echo esc_html($product['panel_opens']); ?></td>

                        <td>
                            <span class="gg-admin-product-signal">
                                <?php echo esc_html($product['signal']); ?>
                            </span>
                        </td>
                    </tr>
                <?php endforeach; ?>
            <?php else : ?>
                <tr>
                    <td colspan="6">Inga produktinteraktioner har loggats ännu.</td>
                </tr>
            <?php endif; ?>
        </tbody>
    </table>

    <?php
    return ob_get_clean();
}

/**
 * Gold Goblins Aktivitetslogg
 */
/**
 * Gold Goblins Aktivitetslogg
 */

add_action('init', 'gg_activity_install_table', 5);

function gg_activity_install_table() {
    global $wpdb;

    $version = '1.0.0';

    if (get_option('gg_activity_log_db_version') === $version) {
        return;
    }

    $table_name = $wpdb->prefix . 'gg_activity_log';
    $charset_collate = $wpdb->get_charset_collate();

    require_once ABSPATH . 'wp-admin/includes/upgrade.php';

    $sql = "CREATE TABLE {$table_name} (
        id bigint(20) unsigned NOT NULL AUTO_INCREMENT,
        event_type varchar(80) NOT NULL,
        event_label varchar(190) NOT NULL DEFAULT '',
        object_id bigint(20) unsigned NOT NULL DEFAULT 0,
        object_type varchar(80) NOT NULL DEFAULT '',
        session_key varchar(64) NOT NULL DEFAULT '',
        user_id bigint(20) unsigned NOT NULL DEFAULT 0,
        page_url varchar(500) NOT NULL DEFAULT '',
        referrer varchar(500) NOT NULL DEFAULT '',
        meta longtext NULL,
        created_at datetime NOT NULL,
        PRIMARY KEY  (id),
        KEY event_type_created (event_type, created_at),
        KEY object_lookup (object_type, object_id),
        KEY session_created (session_key, created_at)
    ) {$charset_collate};";

    dbDelta($sql);

    update_option('gg_activity_log_db_version', $version, false);
}


function gg_activity_get_session_key() {
    if (!empty($_COOKIE['gg_activity_session'])) {
        $session_key = sanitize_text_field(wp_unslash($_COOKIE['gg_activity_session']));

        if (preg_match('/^[a-f0-9]{64}$/', $session_key)) {
            return $session_key;
        }
    }

    $session_key = hash_hmac(
        'sha256',
        wp_generate_uuid4() . '|' . microtime(true) . '|' . wp_rand(),
        wp_salt('auth')
    );

    if (!headers_sent()) {
        setcookie(
            'gg_activity_session',
            $session_key,
            time() + (30 * DAY_IN_SECONDS),
            COOKIEPATH ? COOKIEPATH : '/',
            COOKIE_DOMAIN,
            is_ssl(),
            true
        );
    }

    $_COOKIE['gg_activity_session'] = $session_key;

    return $session_key;
}


function gg_activity_should_ignore_request() {
    if (is_user_logged_in() && current_user_can('manage_options')) {
        return true;
    }

    $user_agent = isset($_SERVER['HTTP_USER_AGENT'])
        ? strtolower(sanitize_text_field(wp_unslash($_SERVER['HTTP_USER_AGENT'])))
        : '';

    if (!$user_agent) {
        return true;
    }

    $bots = [
        'bot',
        'crawl',
        'spider',
        'slurp',
        'facebookexternalhit',
        'preview',
        'monitor',
        'uptime',
    ];

    foreach ($bots as $bot) {
        if (strpos($user_agent, $bot) !== false) {
            return true;
        }
    }

    return false;
}


function gg_activity_sanitize_meta($value) {
    if (is_array($value)) {
        $clean = [];

        foreach ($value as $key => $item) {
            $clean[sanitize_key($key)] = gg_activity_sanitize_meta($item);
        }

        return $clean;
    }

    if (is_scalar($value)) {
        return sanitize_text_field((string) $value);
    }

    return '';
}


function gg_activity_log_event($event_type, $args = []) {
    if (gg_activity_should_ignore_request()) {
        return false;
    }

    global $wpdb;

    $event_type = sanitize_key($event_type);

    if (!$event_type) {
        return false;
    }

    $table_name = $wpdb->prefix . 'gg_activity_log';

    $event_label = isset($args['event_label'])
        ? sanitize_text_field($args['event_label'])
        : '';

    $object_id = isset($args['object_id'])
        ? absint($args['object_id'])
        : 0;

    $object_type = isset($args['object_type'])
        ? sanitize_key($args['object_type'])
        : '';

    $page_url = isset($args['page_url'])
        ? esc_url_raw($args['page_url'])
        : gg_activity_get_current_url();

    $referrer = isset($args['referrer'])
        ? esc_url_raw($args['referrer'])
        : wp_get_referer();

    $meta = isset($args['meta']) && is_array($args['meta'])
        ? gg_activity_sanitize_meta($args['meta'])
        : [];

    $inserted = $wpdb->insert(
        $table_name,
        [
            'event_type'  => $event_type,
            'event_label' => $event_label,
            'object_id'   => $object_id,
            'object_type' => $object_type,
            'session_key' => gg_activity_get_session_key(),
            'user_id'     => get_current_user_id(),
            'page_url'    => $page_url ? $page_url : '',
            'referrer'    => $referrer ? $referrer : '',
            'meta'        => !empty($meta) ? wp_json_encode($meta) : '',
            'created_at'  => current_time('mysql'),
        ],
        [
            '%s',
            '%s',
            '%d',
            '%s',
            '%s',
            '%d',
            '%s',
            '%s',
            '%s',
            '%s',
        ]
    );

    return (bool) $inserted;
}


function gg_activity_get_current_url() {
    $scheme = is_ssl() ? 'https://' : 'http://';

    $host = isset($_SERVER['HTTP_HOST'])
        ? sanitize_text_field(wp_unslash($_SERVER['HTTP_HOST']))
        : '';

    $uri = isset($_SERVER['REQUEST_URI'])
        ? sanitize_text_field(wp_unslash($_SERVER['REQUEST_URI']))
        : '';

    if (!$host) {
        return home_url('/');
    }

    return esc_url_raw($scheme . $host . $uri);
}


add_action('wp_ajax_gg_log_activity', 'gg_activity_ajax_log_event');
add_action('wp_ajax_nopriv_gg_log_activity', 'gg_activity_ajax_log_event');

function gg_activity_ajax_log_event() {
    if (
        empty($_POST['nonce']) ||
        !wp_verify_nonce(sanitize_text_field(wp_unslash($_POST['nonce'])), 'gg_activity_log_nonce')
    ) {
        wp_send_json_error([
            'message' => 'Säkerhetskontrollen misslyckades.',
        ], 403);
    }

    $event_type = isset($_POST['event_type'])
        ? sanitize_key(wp_unslash($_POST['event_type']))
        : '';

    $allowed_events = [
    'page_view',
    'product_view',
    'cart_open',
    'product_gallery_click',
    'info_panel_open',
    'contact_form_start',
    'contact_form_submit',
    'design_form_start',
    'design_form_submit',
];

    if (!in_array($event_type, $allowed_events, true)) {
        wp_send_json_error([
            'message' => 'Ogiltig händelse.',
        ], 400);
    }

    $session_key = gg_activity_get_session_key();
    $rate_key = 'gg_activity_rate_' . $session_key . '_' . $event_type;
    $rate_count = (int) get_transient($rate_key);

    if ($rate_count >= 60) {
        wp_send_json_success([
            'logged' => false,
            'reason' => 'rate_limited',
        ]);
    }

    set_transient($rate_key, $rate_count + 1, 5 * MINUTE_IN_SECONDS);

    $meta = [];

    if (!empty($_POST['meta'])) {
        $raw_meta = wp_unslash($_POST['meta']);
        $decoded_meta = json_decode($raw_meta, true);

        if (is_array($decoded_meta)) {
            $meta = $decoded_meta;
        }
    }

    gg_activity_log_event($event_type, [
        'event_label' => isset($_POST['event_label'])
            ? sanitize_text_field(wp_unslash($_POST['event_label']))
            : '',
        'object_id' => isset($_POST['object_id'])
            ? absint($_POST['object_id'])
            : 0,
        'object_type' => isset($_POST['object_type'])
            ? sanitize_key(wp_unslash($_POST['object_type']))
            : '',
        'page_url' => isset($_POST['page_url'])
            ? esc_url_raw(wp_unslash($_POST['page_url']))
            : '',
        'referrer' => isset($_POST['referrer'])
            ? esc_url_raw(wp_unslash($_POST['referrer']))
            : '',
        'meta' => $meta,
    ]);

    wp_send_json_success([
        'logged' => true,
    ]);
}


add_action('wp_footer', 'gg_activity_frontend_script', 99);

function gg_activity_frontend_script() {
    if (is_admin()) {
        return;
    }

    $post_id = is_singular() ? get_queried_object_id() : 0;
    $post_type = $post_id ? get_post_type($post_id) : '';
    ?>

    <script>
    (function(){
        const ggActivityConfig = {
            ajaxUrl: <?php echo wp_json_encode(admin_url('admin-ajax.php')); ?>,
            nonce: <?php echo wp_json_encode(wp_create_nonce('gg_activity_log_nonce')); ?>,
            postId: <?php echo (int) $post_id; ?>,
            postType: <?php echo wp_json_encode($post_type); ?>,
            pageUrl: window.location.href,
            referrer: document.referrer || ''
        };

        function ggActivityFindProductId(context) {
            const root = context || document;
            const form = root.closest && root.closest('form.cart')
                ? root.closest('form.cart')
                : document.querySelector('#gg-product-detail form.cart, form.cart');

            if (!form) {
                return '';
            }

            const productInput = form.querySelector('[name="product_id"]');
            const addToCartInput = form.querySelector('[name="add-to-cart"]');
            const addButton = form.querySelector('.single_add_to_cart_button');

            return (
                productInput && productInput.value ||
                addToCartInput && addToCartInput.value ||
                addButton && addButton.value ||
                ''
            );
        }

        function ggActivityGetProductTitle() {
            const title =
                document.querySelector('#gg-product-detail h1') ||
                document.querySelector('.product_title') ||
                document.querySelector('h1');

            return title ? title.textContent.trim() : document.title;
        }

        function ggActivityLog(eventType, data, onceKey) {
            if (onceKey) {
                const storageKey = 'gg_activity_' + onceKey;

                try {
                    if (sessionStorage.getItem(storageKey)) {
                        return;
                    }

                    sessionStorage.setItem(storageKey, '1');
                } catch(error) {}
            }

            const formData = new FormData();

            formData.append('action', 'gg_log_activity');
            formData.append('nonce', ggActivityConfig.nonce);
            formData.append('event_type', eventType);
            formData.append('event_label', data && data.eventLabel ? data.eventLabel : '');
            formData.append('object_id', data && data.objectId ? data.objectId : '');
            formData.append('object_type', data && data.objectType ? data.objectType : '');
            formData.append('page_url', ggActivityConfig.pageUrl);
            formData.append('referrer', ggActivityConfig.referrer);
            formData.append('meta', JSON.stringify(data && data.meta ? data.meta : {}));

            fetch(ggActivityConfig.ajaxUrl, {
                method: 'POST',
                body: formData,
                credentials: 'same-origin',
                keepalive: true
            }).catch(function(){});
        }

        document.addEventListener('DOMContentLoaded', function(){
    ggActivityLog('page_view', {
        eventLabel: document.title || window.location.pathname,
        objectId: ggActivityConfig.postId,
        objectType: ggActivityConfig.postType || 'page',
        meta: {
            path: window.location.pathname
        }
    });

    const productDetail = document.getElementById('gg-product-detail');
    const isWooProduct = document.body.classList.contains('single-product');

    if (productDetail || isWooProduct) {
                const productId = ggActivityFindProductId(document);

                ggActivityLog('product_view', {
                    eventLabel: ggActivityGetProductTitle(),
                    objectId: productId || ggActivityConfig.postId,
                    objectType: 'product',
                    meta: {
                        page_post_id: ggActivityConfig.postId,
                        page_post_type: ggActivityConfig.postType
                    }
                }, 'product_view_' + (productId || ggActivityConfig.postId || window.location.pathname));
            }
        });

        document.addEventListener('click', function(e){
            const cartTrigger = e.target.closest('.gg-cart-trigger');

            if (cartTrigger) {
                ggActivityLog('cart_open', {
                    eventLabel: 'Varukorg öppnad',
                    objectId: ggActivityConfig.postId,
                    objectType: ggActivityConfig.postType,
                    meta: {
                        source: 'header_cart'
                    }
                });
            }

            const thumb = e.target.closest('.gg-thumb');

            if (thumb) {
                const productId = ggActivityFindProductId(thumb);

                ggActivityLog('product_gallery_click', {
                    eventLabel: ggActivityGetProductTitle(),
                    objectId: productId || ggActivityConfig.postId,
                    objectType: 'product',
                    meta: {
                        image: thumb.getAttribute('data-large') || thumb.getAttribute('src') || ''
                    }
                });
            }

            const panelLink = e.target.closest('.gg-open-panel');

            if (panelLink) {
                ggActivityLog('info_panel_open', {
                    eventLabel: panelLink.textContent.trim(),
                    objectId: ggActivityFindProductId(panelLink) || ggActivityConfig.postId,
                    objectType: ggActivityConfig.postType,
                    meta: {
                        panel: panelLink.dataset.panel || ''
                    }
                });
            }
        });

        document.addEventListener('focusin', function(e){
            const contactForm = e.target.closest('.gg-contact-form');

            if (contactForm) {
                ggActivityLog('contact_form_start', {
                    eventLabel: 'Kontaktformulär påbörjat',
                    objectId: ggActivityConfig.postId,
                    objectType: ggActivityConfig.postType
                }, 'contact_form_start_' + ggActivityConfig.postId);
            }

            const designForm = e.target.closest('.gg-design-form');

            if (designForm) {
                ggActivityLog('design_form_start', {
                    eventLabel: 'Designformulär påbörjat',
                    objectId: ggActivityConfig.postId,
                    objectType: ggActivityConfig.postType
                }, 'design_form_start_' + ggActivityConfig.postId);
            }
        });

        document.addEventListener('submit', function(e){
            const contactForm = e.target.closest('.gg-contact-form');

            if (contactForm) {
                ggActivityLog('contact_form_submit', {
                    eventLabel: 'Kontaktformulär skickat',
                    objectId: ggActivityConfig.postId,
                    objectType: ggActivityConfig.postType
                });
            }

            const designForm = e.target.closest('.gg-design-form');

            if (designForm) {
                ggActivityLog('design_form_submit', {
                    eventLabel: 'Designformulär skickat',
                    objectId: ggActivityConfig.postId,
                    objectType: ggActivityConfig.postType
                });
            }
        }, true);
    })();
    </script>

    <?php
}


add_action('woocommerce_add_to_cart', 'gg_activity_log_add_to_cart', 20, 6);

function gg_activity_log_add_to_cart($cart_item_key, $product_id, $quantity, $variation_id, $variation, $cart_item_data) {
    if (!class_exists('WooCommerce')) {
        return;
    }

    $product = wc_get_product($variation_id ? $variation_id : $product_id);

    gg_activity_log_event('add_to_cart', [
        'event_label' => $product ? $product->get_name() : 'Produkt',
        'object_id'   => $product_id,
        'object_type' => 'product',
        'meta'        => [
            'quantity'     => (int) $quantity,
            'variation_id' => (int) $variation_id,
        ],
    ]);
}


add_action('woocommerce_checkout_order_processed', 'gg_activity_log_order_created', 20, 3);

function gg_activity_log_order_created($order_id, $posted_data, $order) {
    if (!class_exists('WooCommerce')) {
        return;
    }

    if (!$order || !is_a($order, 'WC_Order')) {
        $order = wc_get_order($order_id);
    }

    if (!$order) {
        return;
    }

    gg_activity_log_event('order_created', [
        'event_label' => 'Order #' . $order->get_order_number(),
        'object_id'   => $order_id,
        'object_type' => 'shop_order',
        'meta'        => [
            'total'  => $order->get_total(),
            'status' => $order->get_status(),
        ],
    ]);
}


add_action('wp_insert_post', 'gg_activity_log_created_posts', 30, 3);

function gg_activity_log_created_posts($post_id, $post, $update) {
    if ($update || wp_is_post_revision($post_id)) {
        return;
    }

    if (!$post || empty($post->post_type)) {
        return;
    }

    if ($post->post_type === 'gg_contact_message') {
        gg_activity_log_event('contact_message_created', [
            'event_label' => $post->post_title,
            'object_id'   => $post_id,
            'object_type' => 'gg_contact_message',
        ]);
    }

    if ($post->post_type === 'gg_customer_design') {
        gg_activity_log_event('design_request_created', [
            'event_label' => $post->post_title,
            'object_id'   => $post_id,
            'object_type' => 'gg_customer_design',
        ]);
    }
}


function gg_activity_get_event_name($event_type) {
    $names = [
		'page_view' 			  => 'Sidvisning',
        'product_view'            => 'Produkt visad',
        'add_to_cart'             => 'Lagt i varukorg',
        'cart_open'               => 'Varukorg öppnad',
        'product_gallery_click'   => 'Produktbild klickad',
        'info_panel_open'         => 'Panel öppnad',
        'contact_form_start'      => 'Kontaktformulär påbörjat',
        'contact_form_submit'     => 'Kontaktformulär skickat',
        'contact_message_created' => 'Kontaktmeddelande sparat',
        'design_form_start'       => 'Designformulär påbörjat',
        'design_form_submit'      => 'Designformulär skickat',
        'design_request_created'  => 'Designförfrågan sparad',
        'order_created'           => 'Order skapad',
    ];

    return $names[$event_type] ?? $event_type;
}


function gg_activity_get_event_link($row) {
    $object_id = isset($row->object_id) ? absint($row->object_id) : 0;
    $object_type = isset($row->object_type) ? sanitize_key($row->object_type) : '';

    if ($object_type === 'shop_order' && class_exists('WooCommerce')) {
        $order = wc_get_order($object_id);

        if ($order) {
            return $order->get_edit_order_url();
        }
    }

    if ($object_id && in_array($object_type, ['product', 'gg_contact_message', 'gg_customer_design'], true)) {
        $edit_link = get_edit_post_link($object_id);

        if ($edit_link) {
            return $edit_link;
        }
    }

    if (!empty($row->page_url)) {
        return esc_url($row->page_url);
    }

    return '';
}


function gg_activity_get_recent_rows($limit = 50) {
    global $wpdb;

    $limit = max(1, min(200, absint($limit)));
    $table_name = $wpdb->prefix . 'gg_activity_log';

    return $wpdb->get_results(
        $wpdb->prepare(
            "SELECT *
             FROM {$table_name}
             ORDER BY created_at DESC
             LIMIT %d",
            $limit
        )
    );
}


function gg_activity_get_admin_activity_items($limit = 12) {
    $rows = gg_activity_get_recent_rows($limit);
    $items = [];

    foreach ($rows as $row) {
        $event_name = gg_activity_get_event_name($row->event_type);
        $title = $event_name;

        if (!empty($row->event_label)) {
            $title .= ' – ' . $row->event_label;
        }

        $items[] = [
            'time'      => strtotime($row->created_at),
            'type'      => $event_name,
            'title'     => $title,
            'status'    => 'Loggad',
            'edit_link' => gg_activity_get_event_link($row),
        ];
    }

    return $items;
}


add_action('admin_menu', 'gg_activity_register_admin_page', 40);

function gg_activity_register_admin_page() {
    add_submenu_page(
        'gg-admin-overview',
        'Aktivitetslogg',
        'Aktivitetslogg',
        'manage_options',
        'gg-activity-log',
        'gg_activity_render_admin_page'
    );
}


function gg_activity_render_admin_page() {
    if (!current_user_can('manage_options')) {
        wp_die('Du har inte behörighet att visa denna sida.');
    }

    $rows = gg_activity_get_recent_rows(100);
    ?>

    <div class="wrap">
        <h1>Gold Goblins Aktivitetslogg</h1>
        <p>De senaste loggade kundinteraktionerna på webbplatsen.</p>

        <table class="widefat striped">
            <thead>
                <tr>
                    <th>Tid</th>
                    <th>Händelse</th>
                    <th>Objekt</th>
                    <th>Sida</th>
                </tr>
            </thead>

            <tbody>
                <?php if (!empty($rows)) : ?>
                    <?php foreach ($rows as $row) : ?>
                        <?php
                        $link = gg_activity_get_event_link($row);
                        $title = gg_activity_get_event_name($row->event_type);

                        if (!empty($row->event_label)) {
                            $title .= ' – ' . $row->event_label;
                        }
                        ?>

                        <tr>
                            <td><?php echo esc_html(date_i18n('Y-m-d H:i', strtotime($row->created_at))); ?></td>

                            <td>
                                <?php if ($link) : ?>
                                    <a href="<?php echo esc_url($link); ?>">
                                        <?php echo esc_html($title); ?>
                                    </a>
                                <?php else : ?>
                                    <?php echo esc_html($title); ?>
                                <?php endif; ?>
                            </td>

                            <td>
                                <?php
                                echo esc_html($row->object_type ? $row->object_type : '—');

                                if (!empty($row->object_id)) {
                                    echo ' #' . esc_html($row->object_id);
                                }
                                ?>
                            </td>

                            <td>
                                <?php if (!empty($row->page_url)) : ?>
                                    <a href="<?php echo esc_url($row->page_url); ?>" target="_blank" rel="noopener noreferrer">
                                        Öppna sida
                                    </a>
                                <?php else : ?>
                                    —
                                <?php endif; ?>
                            </td>
                        </tr>
                    <?php endforeach; ?>
                <?php else : ?>
                    <tr>
                        <td colspan="4">Inga aktiviteter har loggats ännu.</td>
                    </tr>
                <?php endif; ?>
            </tbody>
        </table>
    </div>

    <?php
}


/**
 * Gold Goblins Aktivitetsstatistik
 */
if (!function_exists('gg_activity_table_exists')) {
    function gg_activity_table_exists() {
        global $wpdb;

        $table_name = $wpdb->prefix . 'gg_activity_log';

        return $wpdb->get_var(
            $wpdb->prepare(
                'SHOW TABLES LIKE %s',
                $table_name
            )
        ) === $table_name;
    }
}


if (!function_exists('gg_activity_count_events')) {
    function gg_activity_count_events($event_types, $since = '') {
        if (!gg_activity_table_exists()) {
            return 0;
        }

        global $wpdb;

        $table_name = $wpdb->prefix . 'gg_activity_log';
        $event_types = (array) $event_types;
        $event_types = array_filter(array_map('sanitize_key', $event_types));

        if (empty($event_types)) {
            return 0;
        }

        $placeholders = implode(',', array_fill(0, count($event_types), '%s'));

        $sql = "SELECT COUNT(*)
                FROM {$table_name}
                WHERE event_type IN ({$placeholders})";

        $params = $event_types;

        if ($since) {
            $sql .= " AND created_at >= %s";
            $params[] = sanitize_text_field($since);
        }

        return (int) $wpdb->get_var(
            $wpdb->prepare($sql, $params)
        );
    }
}


if (!function_exists('gg_activity_count_unique_sessions')) {
    function gg_activity_count_unique_sessions($since = '') {
        if (!gg_activity_table_exists()) {
            return 0;
        }

        global $wpdb;

        $table_name = $wpdb->prefix . 'gg_activity_log';

        $sql = "SELECT COUNT(DISTINCT session_key)
                FROM {$table_name}
                WHERE session_key != ''";

        $params = [];

        if ($since) {
            $sql .= " AND created_at >= %s";
            $params[] = sanitize_text_field($since);
        }

        if (!empty($params)) {
            return (int) $wpdb->get_var(
                $wpdb->prepare($sql, $params)
            );
        }

        return (int) $wpdb->get_var($sql);
    }
}

/**
 * Gold Goblins Mest interagerade produkter
 */
if (!function_exists('gg_activity_get_product_interaction_rows')) {
    function gg_activity_get_product_interaction_rows($days = 7, $limit = 8) {
        if (!function_exists('gg_activity_table_exists') || !gg_activity_table_exists()) {
            return [];
        }

        global $wpdb;

        $days = max(1, absint($days));
        $limit = max(1, min(30, absint($limit)));

        $table_name = $wpdb->prefix . 'gg_activity_log';

        $since = date_i18n(
            'Y-m-d H:i:s',
            strtotime('-' . $days . ' days', current_time('timestamp'))
        );

        $rows = $wpdb->get_results(
            $wpdb->prepare(
                "SELECT
                    object_id AS product_id,

                    SUM(CASE WHEN event_type = 'product_view' THEN 1 ELSE 0 END) AS product_views,
                    SUM(CASE WHEN event_type = 'add_to_cart' THEN 1 ELSE 0 END) AS add_to_cart,
                    SUM(CASE WHEN event_type = 'product_gallery_click' THEN 1 ELSE 0 END) AS gallery_clicks,
                    SUM(CASE WHEN event_type = 'info_panel_open' THEN 1 ELSE 0 END) AS panel_opens,

                    SUM(
                        CASE
                            WHEN event_type = 'add_to_cart' THEN 4
                            WHEN event_type = 'info_panel_open' THEN 2
                            WHEN event_type = 'product_gallery_click' THEN 2
                            WHEN event_type = 'product_view' THEN 1
                            ELSE 0
                        END
                    ) AS interaction_score,

                    MAX(created_at) AS last_activity

                FROM {$table_name}

                WHERE object_type = 'product'
                AND object_id > 0
                AND event_type IN (
                    'product_view',
                    'add_to_cart',
                    'product_gallery_click',
                    'info_panel_open'
                )
                AND created_at >= %s

                GROUP BY object_id

                ORDER BY interaction_score DESC, last_activity DESC

                LIMIT %d",
                $since,
                $limit
            ),
            ARRAY_A
        );

        if (empty($rows)) {
            return [];
        }

        $products = [];

        foreach ($rows as $row) {
            $product_id = absint($row['product_id']);

            if (!$product_id) {
                continue;
            }

            $product = class_exists('WooCommerce') && function_exists('wc_get_product')
                ? wc_get_product($product_id)
                : null;

            $product_name = $product
                ? $product->get_name()
                : get_the_title($product_id);

            if (!$product_name) {
                $product_name = 'Produkt #' . $product_id;
            }

            $image_id = $product
                ? $product->get_image_id()
                : get_post_thumbnail_id($product_id);

            $product_views = absint($row['product_views']);
            $add_to_cart = absint($row['add_to_cart']);
            $gallery_clicks = absint($row['gallery_clicks']);
            $panel_opens = absint($row['panel_opens']);

            $products[] = [
                'product_id'        => $product_id,
                'product_name'      => $product_name,
                'image_id'          => $image_id,
                'edit_link'         => get_edit_post_link($product_id),
                'permalink'         => get_permalink($product_id),
                'product_views'     => $product_views,
                'add_to_cart'       => $add_to_cart,
                'gallery_clicks'    => $gallery_clicks,
                'panel_opens'       => $panel_opens,
                'interaction_score' => absint($row['interaction_score']),
                'last_activity'     => $row['last_activity'],
                'signal'            => gg_activity_get_product_interaction_signal(
                    $product_views,
                    $add_to_cart,
                    $gallery_clicks,
                    $panel_opens
                ),
            ];
        }

        return $products;
    }
}


if (!function_exists('gg_activity_get_product_interaction_signal')) {
    function gg_activity_get_product_interaction_signal($views, $cart, $gallery, $panels) {
        $views = absint($views);
        $cart = absint($cart);
        $gallery = absint($gallery);
        $panels = absint($panels);

        if ($cart >= 3) {
            return 'Stark köpintent';
        }

        if ($cart >= 1 && $views <= 3) {
            return 'Snabb köpintent';
        }

        if ($views >= 10 && $cart === 0) {
            return 'Många visningar, låg varukorg';
        }

        if ($gallery >= 4 || $panels >= 2) {
            return 'Högt engagemang';
        }

        if ($views >= 3) {
            return 'Växande intresse';
        }

        return 'Normal aktivitet';
    }
}

/**
 * Gold Goblins Aktivitetsrensning
 */
/**
 * Gold Goblins Säker Aktivitetsrensning
 */

add_action('init', 'gg_activity_cleanup_schedule');

function gg_activity_cleanup_schedule() {
    if (!wp_next_scheduled('gg_activity_cleanup_daily')) {
        wp_schedule_event(time() + HOUR_IN_SECONDS, 'daily', 'gg_activity_cleanup_daily');
    }
}


add_action('gg_activity_cleanup_daily', 'gg_activity_cleanup_old_events');

function gg_activity_cleanup_old_events() {
    if (!function_exists('gg_activity_table_exists') || !gg_activity_table_exists()) {
        return;
    }

    /**
     * Viktigt:
     * Innan rådata tas bort ska permanenta totaler och dagligt statistikarkiv uppdateras.
     */
    if (function_exists('gg_activity_totals_process_log_rows')) {
        gg_activity_totals_process_log_rows(5000);
    }

    if (function_exists('gg_activity_daily_archive_process_log_rows')) {
        gg_activity_daily_archive_process_log_rows(5000);
    }

    $rules = gg_activity_cleanup_get_rules();
    $deleted_total = 0;

    foreach ($rules as $event_type => $days) {
        $deleted_total += gg_activity_cleanup_delete_event_type($event_type, $days);
    }

    update_option('gg_activity_cleanup_last_run', current_time('mysql'), false);
    update_option('gg_activity_cleanup_last_deleted_count', $deleted_total, false);
}


function gg_activity_cleanup_get_rules() {
    return [
        /*
         * Sid- och produktvisningar sparas ganska länge i råloggen,
         * eftersom de används för färsk analys och felsökning.
         */
        'page_view'             => 180,
        'product_view'          => 180,

        /*
         * Mikrointeraktioner.
         * De arkiveras dagligen men behöver inte ligga kvar som råhändelser lika länge.
         */
        'product_gallery_click' => 120,
        'cart_open'             => 120,
        'info_panel_open'       => 180,

        /*
         * Formulärstarter visar intent men är inte färdiga kundärenden.
         */
        'contact_form_start'    => 180,
        'design_form_start'     => 180,

        /*
         * Starkare konverteringssignaler sparas längre.
         */
        'add_to_cart'           => 365,
        'contact_form_submit'   => 365,
        'design_form_submit'    => 365,

        /*
         * Dessa har normalt en riktig post/order i WordPress eller WooCommerce.
         * Råloggen behöver inte sparas för alltid.
         */
        'contact_message_created' => 730,
        'design_request_created'  => 730,
        'order_created'           => 730,
    ];
}


function gg_activity_cleanup_delete_event_type($event_type, $days) {
    global $wpdb;

    $event_type = sanitize_key($event_type);
    $days = absint($days);

    if (!$event_type || $days < 30) {
        return 0;
    }

    $table_name = $wpdb->prefix . 'gg_activity_log';

    $before = date_i18n(
        'Y-m-d H:i:s',
        strtotime('-' . $days . ' days', current_time('timestamp'))
    );

    return (int) $wpdb->query(
        $wpdb->prepare(
            "DELETE FROM {$table_name}
             WHERE event_type = %s
             AND created_at < %s",
            $event_type,
            $before
        )
    );
}


function gg_activity_cleanup_count_old_events($event_type, $days) {
    if (!function_exists('gg_activity_table_exists') || !gg_activity_table_exists()) {
        return 0;
    }

    global $wpdb;

    $event_type = sanitize_key($event_type);
    $days = absint($days);

    if (!$event_type || $days < 30) {
        return 0;
    }

    $table_name = $wpdb->prefix . 'gg_activity_log';

    $before = date_i18n(
        'Y-m-d H:i:s',
        strtotime('-' . $days . ' days', current_time('timestamp'))
    );

    return (int) $wpdb->get_var(
        $wpdb->prepare(
            "SELECT COUNT(*)
             FROM {$table_name}
             WHERE event_type = %s
             AND created_at < %s",
            $event_type,
            $before
        )
    );
}


function gg_activity_cleanup_get_event_label($event_type) {
    if (function_exists('gg_activity_get_event_name')) {
        return gg_activity_get_event_name($event_type);
    }

    $labels = [
        'page_view'               => 'Sidvisning',
        'product_view'            => 'Produkt visad',
        'product_gallery_click'   => 'Produktbild klickad',
        'cart_open'               => 'Varukorg öppnad',
        'info_panel_open'         => 'Panel öppnad',
        'contact_form_start'      => 'Kontaktformulär påbörjat',
        'design_form_start'       => 'Designformulär påbörjat',
        'add_to_cart'             => 'Lagt i varukorg',
        'contact_form_submit'     => 'Kontaktformulär skickat',
        'design_form_submit'      => 'Designformulär skickat',
        'contact_message_created' => 'Kontaktmeddelande sparat',
        'design_request_created'  => 'Designförfrågan sparad',
        'order_created'           => 'Order skapad',
    ];

    return $labels[$event_type] ?? $event_type;
}


add_action('admin_menu', 'gg_activity_cleanup_register_admin_page', 45);

function gg_activity_cleanup_register_admin_page() {
    add_submenu_page(
        'gg-admin-overview',
        'Datavård',
        'Datavård',
        'manage_options',
        'gg-activity-cleanup',
        'gg_activity_cleanup_render_admin_page'
    );
}


function gg_activity_cleanup_render_admin_page() {
    if (!current_user_can('manage_options')) {
        wp_die('Du har inte behörighet att visa denna sida.');
    }

    if (
        isset($_POST['gg_activity_cleanup_run']) &&
        check_admin_referer('gg_activity_cleanup_manual_run', 'gg_activity_cleanup_nonce')
    ) {
        gg_activity_cleanup_old_events();

        echo '<div class="notice notice-success is-dismissible"><p>Datavården har körts. Totalräknare och statistikarkiv uppdaterades innan rådata rensades.</p></div>';
    }

    if (
        isset($_POST['gg_activity_archive_only']) &&
        check_admin_referer('gg_activity_cleanup_manual_run', 'gg_activity_cleanup_nonce')
    ) {
        if (function_exists('gg_activity_totals_process_log_rows')) {
            gg_activity_totals_process_log_rows(5000);
        }

        if (function_exists('gg_activity_daily_archive_process_log_rows')) {
            gg_activity_daily_archive_process_log_rows(5000);
        }

        echo '<div class="notice notice-success is-dismissible"><p>Totalräknare och statistikarkiv har uppdaterats utan att rensa rådata.</p></div>';
    }

    $rules = gg_activity_cleanup_get_rules();
    $last_run = get_option('gg_activity_cleanup_last_run');
    $last_deleted = absint(get_option('gg_activity_cleanup_last_deleted_count', 0));
    $next_run = wp_next_scheduled('gg_activity_cleanup_daily');

    global $wpdb;

    $activity_table = $wpdb->prefix . 'gg_activity_log';
    $activity_rows = 0;

    if (function_exists('gg_activity_table_exists') && gg_activity_table_exists()) {
        $activity_rows = (int) $wpdb->get_var("SELECT COUNT(*) FROM {$activity_table}");
    }

    $archive_last_run = get_option('gg_activity_daily_archive_last_run');
    $archive_last_id = absint(get_option('gg_activity_daily_archive_last_log_id', 0));
    $totals_last_id = absint(get_option('gg_activity_totals_last_log_id', 0));
    ?>

    <div class="wrap gg-cleanup-page">
        <h1>Gold Goblins Datavård</h1>

        <p>
            Här rensas gamla detaljerade råhändelser från aktivitetsloggen. Permanenta totalräknare och dagligt statistikarkiv uppdateras alltid innan rensning.
        </p>

        <div class="gg-cleanup-grid">
            <div class="gg-cleanup-card">
                <span>Råhändelser i aktivitetsloggen</span>
                <strong><?php echo esc_html($activity_rows); ?></strong>
                <small>Detaljerad logg som kan rensas över tid</small>
            </div>

            <div class="gg-cleanup-card">
                <span>Senast körd rensning</span>
                <strong><?php echo $last_run ? esc_html(date_i18n('Y-m-d H:i', strtotime($last_run))) : '—'; ?></strong>
                <small>Rader rensade senast: <?php echo esc_html($last_deleted); ?></small>
            </div>

            <div class="gg-cleanup-card">
                <span>Nästa automatiska rensning</span>
                <strong><?php echo $next_run ? esc_html(date_i18n('Y-m-d H:i', $next_run)) : '—'; ?></strong>
                <small>Körs via WordPress cron</small>
            </div>

            <div class="gg-cleanup-card">
                <span>Statistikarkiv</span>
                <strong><?php echo $archive_last_run ? esc_html(date_i18n('Y-m-d H:i', strtotime($archive_last_run))) : '—'; ?></strong>
                <small>Senast arkiverad loggrad: <?php echo esc_html($archive_last_id); ?></small>
            </div>

            <div class="gg-cleanup-card">
                <span>Permanenta totalräknare</span>
                <strong><?php echo esc_html($totals_last_id); ?></strong>
                <small>Senast behandlad loggrad</small>
            </div>
        </div>

        <div class="gg-cleanup-panel">
            <h2>Rensningsregler</h2>

            <table class="widefat striped">
                <thead>
                    <tr>
                        <th>Händelse</th>
                        <th>Sparas som rådata i</th>
                        <th>Rader som kan rensas nu</th>
                    </tr>
                </thead>

                <tbody>
                    <?php foreach ($rules as $event_type => $days) : ?>
                        <tr>
                            <td><?php echo esc_html(gg_activity_cleanup_get_event_label($event_type)); ?></td>
                            <td><?php echo esc_html($days); ?> dagar</td>
                            <td><?php echo esc_html(gg_activity_cleanup_count_old_events($event_type, $days)); ?></td>
                        </tr>
                    <?php endforeach; ?>
                </tbody>
            </table>
        </div>

        <form method="post" class="gg-cleanup-actions">
            <?php wp_nonce_field('gg_activity_cleanup_manual_run', 'gg_activity_cleanup_nonce'); ?>

            <button type="submit" name="gg_activity_archive_only" value="1" class="button">
                Uppdatera arkiv utan rensning
            </button>

            <button type="submit" name="gg_activity_cleanup_run" value="1" class="button button-primary">
                Kör säker rensning nu
            </button>
        </form>

        <div class="gg-cleanup-note">
            <strong>Viktigt:</strong>
            Den här rensningen tar bara bort gamla rader från aktivitetsloggen.
            Den tar inte bort WooCommerce-ordrar, kontaktmeddelanden, kunddesigner, permanenta totalräknare eller statistikarkivet.
        </div>
    </div>

    <style>
        .gg-cleanup-page{
            max-width:1400px;
        }

        .gg-cleanup-page h1{
            color:#2f2b25;
            font-family:Georgia, "Times New Roman", serif;
            font-weight:400;
            font-size:34px;
            margin:18px 0 8px;
        }

        .gg-cleanup-page p{
            color:#6b5a43;
            font-size:13px;
        }

        .gg-cleanup-grid{
            display:grid;
            grid-template-columns:repeat(auto-fit, minmax(220px, 1fr));
            gap:12px;
            margin:18px 0;
        }

        .gg-cleanup-card{
            background:#f1dfc4;
            border:1px solid #c7ab79;
            border-left:3px solid #b9965f;
            padding:14px;
        }

        .gg-cleanup-card span{
            display:block;
            color:#6b5a43;
            font-size:11px;
            text-transform:uppercase;
            letter-spacing:0.08em;
            margin-bottom:8px;
        }

        .gg-cleanup-card strong{
            display:block;
            color:#2f2b25;
            font-family:Georgia, "Times New Roman", serif;
            font-size:22px;
            font-weight:400;
            line-height:1.15;
            margin-bottom:6px;
        }

        .gg-cleanup-card small{
            color:#7a6850;
            font-size:12px;
        }

        .gg-cleanup-panel{
            background:#fff;
            border:1px solid #ddd3c2;
            margin-top:18px;
        }

        .gg-cleanup-panel h2{
            margin:0;
            padding:14px 16px;
            background:#f1dfc4;
            border-bottom:1px solid #ddd3c2;
            color:#2f2b25;
            font-family:Georgia, "Times New Roman", serif;
            font-size:18px;
            font-weight:400;
        }

        .gg-cleanup-panel table{
            border:0;
        }

        .gg-cleanup-actions{
            display:flex;
            gap:10px;
            margin-top:18px;
        }

        .gg-cleanup-note{
            margin-top:18px;
            max-width:900px;
            background:#fff;
            border-left:4px solid #b9965f;
            padding:12px 14px;
            color:#5f4f39;
        }
    </style>

    <?php
}

/**
 * Gold Goblins Permanenta totalräknare
 */
/**
 * Gold Goblins Permanenta totalräknare
 */

add_action('init', 'gg_activity_totals_install_tables', 7);
add_action('init', 'gg_activity_totals_process_log_rows', 30);
add_action('gg_activity_cleanup_daily', 'gg_activity_totals_process_log_rows', 1);

function gg_activity_totals_install_tables() {
    global $wpdb;

    $version = '1.0.0';

    if (get_option('gg_activity_totals_db_version') === $version) {
        return;
    }

    require_once ABSPATH . 'wp-admin/includes/upgrade.php';

    $charset_collate = $wpdb->get_charset_collate();

    $totals_table = $wpdb->prefix . 'gg_activity_totals';
    $sessions_table = $wpdb->prefix . 'gg_activity_total_sessions';

    $sql_totals = "CREATE TABLE {$totals_table} (
        metric_key varchar(120) NOT NULL,
        counter_value bigint(20) unsigned NOT NULL DEFAULT 0,
        updated_at datetime NOT NULL,
        PRIMARY KEY  (metric_key)
    ) {$charset_collate};";

    $sql_sessions = "CREATE TABLE {$sessions_table} (
        session_key varchar(64) NOT NULL,
        first_seen datetime NOT NULL,
        PRIMARY KEY  (session_key)
    ) {$charset_collate};";

    dbDelta($sql_totals);
    dbDelta($sql_sessions);

    update_option('gg_activity_totals_db_version', $version, false);
}


function gg_activity_totals_table_exists($table_name) {
    global $wpdb;

    return $wpdb->get_var(
        $wpdb->prepare(
            'SHOW TABLES LIKE %s',
            $table_name
        )
    ) === $table_name;
}


function gg_activity_totals_process_log_rows($limit = 1000) {
    global $wpdb;

    $activity_table = $wpdb->prefix . 'gg_activity_log';
    $totals_table = $wpdb->prefix . 'gg_activity_totals';
    $sessions_table = $wpdb->prefix . 'gg_activity_total_sessions';

    if (
        !gg_activity_totals_table_exists($activity_table) ||
        !gg_activity_totals_table_exists($totals_table) ||
        !gg_activity_totals_table_exists($sessions_table)
    ) {
        return;
    }

    $limit = max(50, min(5000, absint($limit)));
    $last_id = absint(get_option('gg_activity_totals_last_log_id', 0));

    $rows = $wpdb->get_results(
        $wpdb->prepare(
            "SELECT id, event_type, session_key
             FROM {$activity_table}
             WHERE id > %d
             ORDER BY id ASC
             LIMIT %d",
            $last_id,
            $limit
        )
    );

    if (empty($rows)) {
        return;
    }

    $max_id = $last_id;

    foreach ($rows as $row) {
        $event_type = sanitize_key($row->event_type);

        if ($event_type) {
            gg_activity_totals_increment_metric('event:' . $event_type, 1);
        }

        if (!empty($row->session_key)) {
            gg_activity_totals_register_session($row->session_key);
        }

        $max_id = max($max_id, absint($row->id));
    }

    update_option('gg_activity_totals_last_log_id', $max_id, false);

    if (count($rows) === $limit) {
        gg_activity_totals_process_log_rows($limit);
    }
}


function gg_activity_totals_increment_metric($metric_key, $amount = 1) {
    global $wpdb;

    $metric_key = sanitize_text_field($metric_key);
    $amount = absint($amount);

    if (!$metric_key || $amount < 1) {
        return false;
    }

    $table_name = $wpdb->prefix . 'gg_activity_totals';

    if (!gg_activity_totals_table_exists($table_name)) {
        return false;
    }

    return (bool) $wpdb->query(
        $wpdb->prepare(
            "INSERT INTO {$table_name} (metric_key, counter_value, updated_at)
             VALUES (%s, %d, %s)
             ON DUPLICATE KEY UPDATE
                counter_value = counter_value + VALUES(counter_value),
                updated_at = VALUES(updated_at)",
            $metric_key,
            $amount,
            current_time('mysql')
        )
    );
}


function gg_activity_totals_register_session($session_key) {
    global $wpdb;

    $session_key = sanitize_text_field($session_key);

    if (!preg_match('/^[a-f0-9]{64}$/', $session_key)) {
        return false;
    }

    $sessions_table = $wpdb->prefix . 'gg_activity_total_sessions';

    if (!gg_activity_totals_table_exists($sessions_table)) {
        return false;
    }

    $inserted = $wpdb->query(
        $wpdb->prepare(
            "INSERT IGNORE INTO {$sessions_table} (session_key, first_seen)
             VALUES (%s, %s)",
            $session_key,
            current_time('mysql')
        )
    );

    if ($inserted) {
        gg_activity_totals_increment_metric('unique_sessions', 1);
    }

    return (bool) $inserted;
}


function gg_activity_total_get($event_types) {
    gg_activity_totals_process_log_rows();

    if (is_array($event_types)) {
        $total = 0;

        foreach ($event_types as $event_type) {
            $total += gg_activity_total_get($event_type);
        }

        return $total;
    }

    global $wpdb;

    $event_type = sanitize_key($event_types);

    if (!$event_type) {
        return 0;
    }

    $table_name = $wpdb->prefix . 'gg_activity_totals';

    if (!gg_activity_totals_table_exists($table_name)) {
        return 0;
    }

    return (int) $wpdb->get_var(
        $wpdb->prepare(
            "SELECT counter_value
             FROM {$table_name}
             WHERE metric_key = %s",
            'event:' . $event_type
        )
    );
}


function gg_activity_total_get_unique_sessions() {
    gg_activity_totals_process_log_rows();

    global $wpdb;

    $table_name = $wpdb->prefix . 'gg_activity_totals';

    if (!gg_activity_totals_table_exists($table_name)) {
        return 0;
    }

    return (int) $wpdb->get_var(
        $wpdb->prepare(
            "SELECT counter_value
             FROM {$table_name}
             WHERE metric_key = %s",
            'unique_sessions'
        )
    );
}

/**
 * Gold Goblins Analysdashboard
 */
/**
 * Gold Goblins Analysdashboard
 */

add_action('admin_menu', 'gg_admin_analytics_register_page', 46);

function gg_admin_analytics_register_page() {
    add_submenu_page(
        'gg-admin-overview',
        'Analys',
        'Analys',
        'manage_options',
        'gg-admin-analytics',
        'gg_admin_analytics_render_page'
    );
}


function gg_admin_analytics_render_page() {
    if (!current_user_can('manage_options')) {
        wp_die('Du har inte behörighet att visa denna sida.');
    }

    $nonce = wp_create_nonce('gg_admin_analytics_nonce');
    $ajax_url = admin_url('admin-ajax.php');
    ?>

    <div class="wrap gg-analytics-dashboard">
        <div class="gg-analytics-header">
            <div>
                <h1>Gold Goblins Analys</h1>
                <p>Visuell statistik för sidvisningar, produktintresse, varukorg och försäljning.</p>
            </div>

            <div class="gg-analytics-status" data-gg-analytics-status>
                Laddar statistik...
            </div>
        </div>

        <div class="gg-analytics-controls">
            <div class="gg-analytics-control-group">
                <span>Statistik</span>

                <button type="button" class="is-active" data-gg-metric="page_views">Sidvisningar</button>
                <button type="button" data-gg-metric="product_views">Produktvisningar</button>
                <button type="button" data-gg-metric="add_to_cart">Varukorg</button>
                <button type="button" data-gg-metric="sales">Försäljning</button>
            </div>

            <div class="gg-analytics-control-group">
                <span>Period</span>

                <button type="button" class="is-active" data-gg-period="today">Idag</button>
                <button type="button" data-gg-period="7days">7 dagar</button>
                <button type="button" data-gg-period="30days">30 dagar</button>
                <button type="button" data-gg-period="quarter">Kvartal</button>
                <button type="button" data-gg-period="total">Totalt</button>
            </div>
        </div>

        <div class="gg-analytics-kpis" data-gg-analytics-kpis></div>

        <div class="gg-analytics-main">
            <div class="gg-analytics-panel gg-analytics-line-panel">
                <div class="gg-analytics-panel-header">
                    <h2 data-gg-line-title>Utveckling över tid</h2>
                    <p data-gg-line-subtitle></p>
                </div>

                <div class="gg-analytics-line-chart" data-gg-line-chart></div>
            </div>

            <div class="gg-analytics-panel gg-analytics-donut-panel">
                <div class="gg-analytics-panel-header">
                    <h2 data-gg-donut-title>Fördelning</h2>
                    <p data-gg-donut-subtitle></p>
                </div>

                <div class="gg-analytics-donut-wrap">
                    <div class="gg-analytics-donut" data-gg-donut></div>
                    <div class="gg-analytics-legend" data-gg-legend></div>
                </div>
            </div>
        </div>

        <div class="gg-analytics-panel">
            <div class="gg-analytics-panel-header">
                <h2 data-gg-table-title>Detaljer</h2>
                <p data-gg-table-subtitle></p>
            </div>

            <div class="gg-analytics-table" data-gg-analytics-table></div>
        </div>
    </div>

    <style>
    .gg-analytics-dashboard{
        max-width:1700px;
        margin:0;
    }

    .gg-analytics-header{
        display:flex;
        align-items:flex-end;
        justify-content:space-between;
        gap:18px;
        margin:18px 0 14px;
    }

    .gg-analytics-header h1{
        margin:0 0 4px;
        color:#2f2b25;
        font-family:Georgia, "Times New Roman", serif;
        font-weight:400;
        font-size:32px;
        line-height:1.05;
        letter-spacing:0.01em;
    }

    .gg-analytics-header p{
        margin:0;
        color:#6b5a43;
        font-size:13px;
        line-height:1.45;
    }

    .gg-analytics-status{
        display:inline-flex;
        align-items:center;
        justify-content:center;
        min-height:34px;
        background:#f1dfc4;
        border:1px solid #c7ab79;
        color:#5f4f39;
        padding:8px 13px;
        font-size:12px;
        white-space:nowrap;
        box-shadow:0 1px 3px rgba(0,0,0,0.04);
    }

    .gg-analytics-controls{
        display:flex;
        align-items:center;
        justify-content:space-between;
        gap:14px;
        margin-bottom:14px;
        padding:10px 12px;
        background:#fff;
        border:1px solid #ddd3c2;
        box-shadow:0 1px 4px rgba(0,0,0,0.035);
    }

    .gg-analytics-control-group{
        display:flex;
        align-items:center;
        flex-wrap:wrap;
        gap:6px;
    }

    .gg-analytics-control-group span{
        margin-right:5px;
        color:#6b5a43;
        font-size:11px;
        text-transform:uppercase;
        letter-spacing:0.08em;
    }

    .gg-analytics-control-group button{
        border:1px solid #c7ab79;
        background:#f1dfc4;
        color:#2f2b25;
        padding:6px 10px;
        font-size:12px;
        line-height:1.2;
        cursor:pointer;
        transition:background 0.12s ease, color 0.12s ease, border-color 0.12s ease, transform 0.12s ease;
    }

    .gg-analytics-control-group button:hover{
        border-color:#a78656;
        transform:translateY(-1px);
    }

    .gg-analytics-control-group button.is-active{
        background:#2f2b25;
        border-color:#2f2b25;
        color:#f1dfc4;
    }

    .gg-analytics-kpis{
        display:grid;
        grid-template-columns:repeat(4, minmax(0, 1fr));
        gap:10px;
        margin-bottom:14px;
    }

    .gg-analytics-kpi{
        min-height:82px;
        background:linear-gradient(180deg, #f5e7cd 0%, #f1dfc4 100%);
        border:1px solid #c7ab79;
        border-left:4px solid #b9965f;
        padding:12px 14px;
        box-sizing:border-box;
        box-shadow:0 1px 4px rgba(0,0,0,0.035);
    }

    .gg-analytics-kpi span{
        display:block;
        color:#6b5a43;
        font-size:11px;
        text-transform:uppercase;
        letter-spacing:0.08em;
        margin-bottom:7px;
    }

    .gg-analytics-kpi strong{
        display:block;
        color:#2f2b25;
        font-family:Georgia, "Times New Roman", serif;
        font-size:25px;
        font-weight:400;
        line-height:1.05;
        margin-bottom:5px;
    }

    .gg-analytics-kpi small{
        color:#7a6850;
        font-size:12px;
        line-height:1.35;
    }

    .gg-analytics-main{
        display:grid;
        grid-template-columns:minmax(0, 1.55fr) minmax(360px, 0.75fr);
        gap:14px;
        margin-bottom:14px;
    }

    .gg-analytics-panel{
        background:#fff;
        border:1px solid #ddd3c2;
        box-shadow:0 1px 5px rgba(0,0,0,0.04);
        overflow:hidden;
    }

    .gg-analytics-panel-header{
        display:flex;
        align-items:center;
        justify-content:space-between;
        gap:12px;
        padding:12px 16px;
        border-bottom:1px solid #ddd3c2;
        background:linear-gradient(180deg, #f5e7cd 0%, #f1dfc4 100%);
    }

    .gg-analytics-panel-header h2{
        margin:0;
        color:#2f2b25;
        font-family:Georgia, "Times New Roman", serif;
        font-size:18px;
        font-weight:400;
        line-height:1.15;
    }

    .gg-analytics-panel-header p{
        margin:0;
        color:#6b5a43;
        font-size:12px;
        text-align:right;
        line-height:1.35;
    }

    .gg-analytics-line-chart{
        min-height:310px;
        padding:14px 16px 12px;
        box-sizing:border-box;
        background:
            linear-gradient(180deg, rgba(241,223,196,0.18), rgba(255,255,255,0) 45%),
            #fff;
    }

    .gg-analytics-line-chart svg{
        width:100%;
        height:auto;
        display:block;
        overflow:visible;
    }

    .gg-analytics-empty{
        padding:28px;
        color:#7a6850;
        text-align:center;
        font-size:13px;
    }

    .gg-analytics-donut-wrap{
        display:grid;
        grid-template-columns:185px minmax(0, 1fr);
        gap:18px;
        align-items:center;
        padding:20px 18px;
        min-height:260px;
        box-sizing:border-box;
    }

    .gg-analytics-donut{
        width:178px;
        height:178px;
        border-radius:50%;
        background:#f1dfc4;
        position:relative;
        border:1px solid #c7ab79;
        box-shadow:inset 0 0 0 1px rgba(255,255,255,0.55), 0 2px 8px rgba(0,0,0,0.06);
    }

    .gg-analytics-donut::after{
        content:"";
        position:absolute;
        inset:42px;
        border-radius:50%;
        background:#fff;
        border:1px solid #eee7db;
        z-index:1;
    }

    .gg-analytics-donut-center{
        position:absolute;
        inset:46px;
        z-index:2;
        display:flex;
        flex-direction:column;
        align-items:center;
        justify-content:center;
        text-align:center;
        color:#2f2b25;
        pointer-events:none;
    }

    .gg-analytics-donut-center strong{
        display:block;
        font-family:Georgia, "Times New Roman", serif;
        font-size:24px;
        font-weight:400;
        line-height:1;
    }

    .gg-analytics-donut-center span{
        display:block;
        margin-top:4px;
        color:#7a6850;
        font-size:10px;
        text-transform:uppercase;
        letter-spacing:0.07em;
    }

    .gg-analytics-legend{
        display:grid;
        gap:8px;
        min-width:0;
    }

    .gg-analytics-legend-row{
        display:grid;
        grid-template-columns:12px minmax(0, 1fr) auto;
        gap:8px;
        align-items:center;
        font-size:12px;
        color:#2f2b25;
        min-width:0;
    }

    .gg-analytics-legend-dot{
        width:10px;
        height:10px;
        border-radius:50%;
        background:#b9965f;
        box-shadow:0 0 0 2px rgba(185,150,95,0.12);
    }

    .gg-analytics-legend-label{
        overflow:hidden;
        text-overflow:ellipsis;
        white-space:nowrap;
        min-width:0;
    }

    .gg-analytics-legend-value{
        color:#6b5a43;
        white-space:nowrap;
        font-variant-numeric:tabular-nums;
    }

    .gg-analytics-table table{
        width:100%;
        border-collapse:collapse;
        table-layout:fixed;
    }

    .gg-analytics-table th,
    .gg-analytics-table td{
        padding:9px 14px;
        border-bottom:1px solid #eee7db;
        text-align:left;
        vertical-align:middle;
        font-size:13px;
        color:#2f2b25;
        word-wrap:break-word;
    }

    .gg-analytics-table th{
        color:#6b5a43;
        font-size:11px;
        text-transform:uppercase;
        letter-spacing:0.08em;
        background:#fbf8f3;
    }

    .gg-analytics-table td.is-number,
    .gg-analytics-table th.is-number{
        text-align:right;
        font-variant-numeric:tabular-nums;
    }

    .gg-analytics-table tbody tr:nth-child(even){
        background:#fcfaf7;
    }

    .gg-analytics-table tbody tr:hover{
        background:#f7f1e7;
    }

    .gg-analytics-table a{
        color:#9f8560;
        text-decoration:none;
    }

    .gg-analytics-table a:hover{
        text-decoration:underline;
    }

    @media(max-width:1200px){
        .gg-analytics-main{
            grid-template-columns:1fr;
        }

        .gg-analytics-kpis{
            grid-template-columns:repeat(2, minmax(0, 1fr));
        }
    }

    @media(max-width:800px){
        .gg-analytics-header,
        .gg-analytics-controls,
        .gg-analytics-panel-header{
            display:block;
        }

        .gg-analytics-status{
            margin-top:10px;
        }

        .gg-analytics-control-group{
            margin-bottom:10px;
        }

        .gg-analytics-donut-wrap{
            grid-template-columns:1fr;
        }
    }

    @media(max-width:640px){
        .gg-analytics-kpis{
            grid-template-columns:1fr;
        }

        .gg-analytics-header h1{
            font-size:28px;
        }
    }
</style>

    <script>
        (function(){
            const ajaxUrl = <?php echo wp_json_encode($ajax_url); ?>;
            const nonce = <?php echo wp_json_encode($nonce); ?>;

            const state = {
                metric: 'page_views',
                period: 'today'
            };

            const colors = [
                '#b9965f',
                '#2f2b25',
                '#8d7551',
                '#d1b47c',
                '#6b5a43',
                '#c7ab79'
            ];

            function escapeHtml(value){
    const div = document.createElement('div');

    if (value === null || typeof value === 'undefined') {
        div.textContent = '';
    } else {
        div.textContent = String(value);
    }

    return div.innerHTML;
}

            function setStatus(text){
                const status = document.querySelector('[data-gg-analytics-status]');

                if (status) {
                    status.textContent = text;
                }
            }

            function setActiveButtons(){
                document.querySelectorAll('[data-gg-metric]').forEach(function(button){
                    button.classList.toggle('is-active', button.dataset.ggMetric === state.metric);
                });

                document.querySelectorAll('[data-gg-period]').forEach(function(button){
                    button.classList.toggle('is-active', button.dataset.ggPeriod === state.period);
                });
            }

            function loadAnalytics(){
                setActiveButtons();
                setStatus('Laddar statistik...');

                const formData = new FormData();

                formData.append('action', 'gg_admin_analytics_get_data');
                formData.append('nonce', nonce);
                formData.append('metric', state.metric);
                formData.append('period', state.period);

                fetch(ajaxUrl, {
                    method: 'POST',
                    credentials: 'same-origin',
                    body: formData
                })
                .then(function(response){
                    return response.json();
                })
                .then(function(response){
                    if (!response || !response.success || !response.data) {
                        setStatus('Kunde inte hämta statistik.');
                        return;
                    }

                    renderDashboard(response.data);
                    setStatus('Uppdaterad: ' + response.data.generated_at);
                })
                .catch(function(){
                    setStatus('Kunde inte hämta statistik.');
                });
            }

            function renderDashboard(data){
                document.querySelector('[data-gg-line-title]').textContent = data.line_title || 'Utveckling över tid';
                document.querySelector('[data-gg-line-subtitle]').textContent = data.period_label || '';

                document.querySelector('[data-gg-donut-title]').textContent = data.donut_title || 'Fördelning';
                document.querySelector('[data-gg-donut-subtitle]').textContent = data.donut_subtitle || '';

                document.querySelector('[data-gg-table-title]').textContent = data.table_title || 'Detaljer';
                document.querySelector('[data-gg-table-subtitle]').textContent = data.table_subtitle || '';

                renderKpis(data.kpis || []);
                renderLineChart(data.series || []);
                renderDonut(data.segments || []);
                renderTable(data.table || { columns: [], rows: [] });
            }

            function renderKpis(kpis){
                const target = document.querySelector('[data-gg-analytics-kpis]');

                if (!target) return;

                target.innerHTML = kpis.map(function(kpi){
                    return `
                        <div class="gg-analytics-kpi">
                            <span>${escapeHtml(kpi.label)}</span>
                            <strong>${escapeHtml(kpi.value)}</strong>
                            <small>${escapeHtml(kpi.description || '')}</small>
                        </div>
                    `;
                }).join('');
            }

            function renderLineChart(series){
    const target = document.querySelector('[data-gg-line-chart]');

    if (!target) return;

    if (!series.length) {
        target.innerHTML = '<div class="gg-analytics-empty">Ingen data för vald period.</div>';
        return;
    }

    const width = 760;
    const height = 300;
    const paddingLeft = 44;
    const paddingRight = 18;
    const paddingTop = 28;
    const paddingBottom = 42;

    const chartWidth = width - paddingLeft - paddingRight;
    const chartHeight = height - paddingTop - paddingBottom;

    const maxValue = Math.max(...series.map(function(point){
        return Number(point.value) || 0;
    }), 1);

    const niceMax = Math.max(1, Math.ceil(maxValue));

    const points = series.map(function(point, index){
        const x = paddingLeft + (series.length === 1 ? chartWidth / 2 : (index / (series.length - 1)) * chartWidth);
        const y = paddingTop + chartHeight - ((Number(point.value) || 0) / niceMax) * chartHeight;

        return {
            x: x,
            y: y,
            label: point.label,
            value: Number(point.value) || 0
        };
    });

    const path = points.map(function(point, index){
        return (index === 0 ? 'M' : 'L') + point.x.toFixed(2) + ' ' + point.y.toFixed(2);
    }).join(' ');

    const areaPath = path + 
        ' L ' + points[points.length - 1].x.toFixed(2) + ' ' + (height - paddingBottom) +
        ' L ' + points[0].x.toFixed(2) + ' ' + (height - paddingBottom) +
        ' Z';

    const labelIndexes = [];

    if (points.length <= 8) {
        points.forEach(function(point, index){
            labelIndexes.push(index);
        });
    } else {
        labelIndexes.push(0);
        labelIndexes.push(Math.floor((points.length - 1) / 2));
        labelIndexes.push(points.length - 1);
    }

    const horizontalGrid = [0, 0.5, 1].map(function(step){
        const y = paddingTop + chartHeight - (step * chartHeight);
        const value = Math.round(niceMax * step);

        return `
            <line x1="${paddingLeft}" y1="${y}" x2="${width - paddingRight}" y2="${y}" stroke="#eee7db" stroke-width="1" />
            <text x="${paddingLeft - 10}" y="${y + 4}" fill="#7a6850" font-size="11" text-anchor="end">${escapeHtml(value)}</text>
        `;
    }).join('');

    target.innerHTML = `
        <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Linjediagram">
            <defs>
                <linearGradient id="ggLineGradient" x1="0" x2="0" y1="0" y2="1">
                    <stop offset="0%" stop-color="#1fa84f" stop-opacity="0.22" />
                    <stop offset="100%" stop-color="#1fa84f" stop-opacity="0" />
                </linearGradient>
            </defs>

            ${horizontalGrid}

            <line x1="${paddingLeft}" y1="${paddingTop}" x2="${paddingLeft}" y2="${height - paddingBottom}" stroke="#ddd3c2" stroke-width="1" />
            <line x1="${paddingLeft}" y1="${height - paddingBottom}" x2="${width - paddingRight}" y2="${height - paddingBottom}" stroke="#ddd3c2" stroke-width="1" />

            <path d="${areaPath}" fill="url(#ggLineGradient)" />
            <path d="${path}" fill="none" stroke="#1fa84f" stroke-width="4.5" stroke-linecap="round" stroke-linejoin="round" />

            ${points.map(function(point){
                const active = point.value > 0;
                return `
                    <circle cx="${point.x}" cy="${point.y}" r="${active ? '4.5' : '3'}" fill="${active ? '#2f2b25' : '#8d7551'}">
                        <title>${escapeHtml(point.label)}: ${escapeHtml(point.value)}</title>
                    </circle>
                `;
            }).join('')}

            ${labelIndexes.map(function(index){
                const point = points[index];

                return `
                    <text x="${point.x}" y="${height - 13}" fill="#6b5a43" font-size="11" text-anchor="${index === 0 ? 'start' : (index === points.length - 1 ? 'end' : 'middle')}">
                        ${escapeHtml(point.label)}
                    </text>
                `;
            }).join('')}
        </svg>
    `;
}

           function renderDonut(segments){
    const donut = document.querySelector('[data-gg-donut]');
    const legend = document.querySelector('[data-gg-legend]');

    if (!donut || !legend) return;

    if (!segments.length) {
        donut.style.background = '#f1dfc4';
        donut.innerHTML = '<div class="gg-analytics-donut-center"><strong>0</strong><span>Totalt</span></div>';
        legend.innerHTML = '<div class="gg-analytics-empty">Ingen fördelning att visa.</div>';
        return;
    }

    const total = segments.reduce(function(sum, segment){
        return sum + (Number(segment.value) || 0);
    }, 0);

    if (!total) {
        donut.style.background = '#f1dfc4';
        donut.innerHTML = '<div class="gg-analytics-donut-center"><strong>0</strong><span>Totalt</span></div>';
        legend.innerHTML = '<div class="gg-analytics-empty">Ingen fördelning att visa.</div>';
        return;
    }

    let start = 0;

    const gradient = segments.map(function(segment, index){
        const value = Number(segment.value) || 0;
        const percent = value / total * 100;
        const end = start + percent;
        const color = colors[index % colors.length];
        const part = `${color} ${start.toFixed(2)}% ${end.toFixed(2)}%`;

        start = end;

        return part;
    }).join(', ');

    donut.style.background = `conic-gradient(${gradient})`;
    donut.innerHTML = `
        <div class="gg-analytics-donut-center">
            <strong>${escapeHtml(total)}</strong>
            <span>Totalt</span>
        </div>
    `;

    legend.innerHTML = segments.map(function(segment, index){
        const value = Number(segment.value) || 0;
        const percent = total ? Math.round(value / total * 100) : 0;
        const color = colors[index % colors.length];

        return `
            <div class="gg-analytics-legend-row">
                <span class="gg-analytics-legend-dot" style="background:${color}"></span>
                <span class="gg-analytics-legend-label" title="${escapeHtml(segment.label)}">${escapeHtml(segment.label)}</span>
                <span class="gg-analytics-legend-value">${escapeHtml(value)} · ${escapeHtml(percent)}%</span>
            </div>
        `;
    }).join('');
}

            function renderTable(table){
                const target = document.querySelector('[data-gg-analytics-table]');

                if (!target) return;

                const columns = table.columns || [];
                const rows = table.rows || [];

                if (!columns.length || !rows.length) {
                    target.innerHTML = '<div class="gg-analytics-empty">Ingen tabell-data för vald period.</div>';
                    return;
                }

                const thead = columns.map(function(column){
                    return `<th class="${column.type === 'number' ? 'is-number' : ''}">${escapeHtml(column.label)}</th>`;
                }).join('');

                const tbody = rows.map(function(row){
                    return `
                        <tr>
                            ${columns.map(function(column){
                                const value = row[column.key] ?? '';
                                const displayValue = column.html ? value : escapeHtml(value);

                                return `<td class="${column.type === 'number' ? 'is-number' : ''}">${displayValue}</td>`;
                            }).join('')}
                        </tr>
                    `;
                }).join('');

                target.innerHTML = `
                    <table>
                        <thead>
                            <tr>${thead}</tr>
                        </thead>
                        <tbody>${tbody}</tbody>
                    </table>
                `;
            }

            document.addEventListener('click', function(e){
                const metricButton = e.target.closest('[data-gg-metric]');
                const periodButton = e.target.closest('[data-gg-period]');

                if (metricButton) {
                    state.metric = metricButton.dataset.ggMetric;
                    loadAnalytics();
                }

                if (periodButton) {
                    state.period = periodButton.dataset.ggPeriod;
                    loadAnalytics();
                }
            });

            loadAnalytics();
        })();
    </script>

    <?php
}


add_action('wp_ajax_gg_admin_analytics_get_data', 'gg_admin_analytics_ajax_get_data');

function gg_admin_analytics_ajax_get_data() {
    if (!current_user_can('manage_options')) {
        wp_send_json_error([
            'message' => 'Du har inte behörighet.',
        ], 403);
    }

    if (
        empty($_POST['nonce']) ||
        !wp_verify_nonce(sanitize_text_field(wp_unslash($_POST['nonce'])), 'gg_admin_analytics_nonce')
    ) {
        wp_send_json_error([
            'message' => 'Säkerhetskontrollen misslyckades.',
        ], 403);
    }

    $metric = isset($_POST['metric'])
        ? sanitize_key(wp_unslash($_POST['metric']))
        : 'page_views';

    $period = isset($_POST['period'])
        ? sanitize_key(wp_unslash($_POST['period']))
        : 'today';

    $allowed_metrics = ['page_views', 'product_views', 'add_to_cart', 'sales'];
    $allowed_periods = ['today', '7days', '30days', 'quarter', 'total'];

    if (!in_array($metric, $allowed_metrics, true)) {
        $metric = 'page_views';
    }

    if (!in_array($period, $allowed_periods, true)) {
        $period = 'today';
    }

    if ($metric === 'sales') {
        wp_send_json_success(gg_admin_analytics_get_sales_data($period));
    }

    $event_map = [
        'page_views'    => 'page_view',
        'product_views' => 'product_view',
        'add_to_cart'   => 'add_to_cart',
    ];

    wp_send_json_success(
        gg_admin_analytics_get_activity_data($metric, $event_map[$metric], $period)
    );
}


function gg_admin_analytics_get_period_info($period) {
    $now = current_time('timestamp');
    $today_start = strtotime(date_i18n('Y-m-d 00:00:00', $now));

    if ($period === 'today') {
        return [
            'key'        => 'today',
            'label'      => 'Idag',
            'start'      => $today_start,
            'group'      => 'hour',
            'bucket_sql' => "DATE_FORMAT(created_at, '%Y-%m-%d %H:00:00')",
            'label_sql'  => "DATE_FORMAT(created_at, '%H:00')",
        ];
    }

    if ($period === '7days') {
        return [
            'key'        => '7days',
            'label'      => 'Senaste 7 dagarna',
            'start'      => strtotime('-6 days', $today_start),
            'group'      => 'day',
            'bucket_sql' => "DATE(created_at)",
            'label_sql'  => "DATE_FORMAT(created_at, '%d/%m')",
        ];
    }

    if ($period === '30days') {
        return [
            'key'        => '30days',
            'label'      => 'Senaste 30 dagarna',
            'start'      => strtotime('-29 days', $today_start),
            'group'      => 'day',
            'bucket_sql' => "DATE(created_at)",
            'label_sql'  => "DATE_FORMAT(created_at, '%d/%m')",
        ];
    }

    if ($period === 'quarter') {
        return [
            'key'        => 'quarter',
            'label'      => 'Senaste kvartalet',
            'start'      => strtotime('-89 days', $today_start),
            'group'      => 'day',
            'bucket_sql' => "DATE(created_at)",
            'label_sql'  => "DATE_FORMAT(created_at, '%d/%m')",
        ];
    }

    return [
        'key'        => 'total',
        'label'      => 'Totalt',
        'start'      => 0,
        'group'      => 'month',
        'bucket_sql' => "DATE_FORMAT(created_at, '%Y-%m-01')",
        'label_sql'  => "DATE_FORMAT(created_at, '%Y-%m')",
    ];
}


function gg_admin_analytics_get_activity_data($metric, $event_type, $period) {
    global $wpdb;

    $period_info = gg_admin_analytics_get_period_info($period);

    if (!function_exists('gg_activity_daily_archive_get_total')) {
        return gg_admin_analytics_empty_data('Statistikarkivet är inte aktivt.');
    }

    $titles = [
        'page_views'    => ['Sidvisningar', 'Toppsidor'],
        'product_views' => ['Produktvisningar', 'Mest visade produkter'],
        'add_to_cart'   => ['Varukorg', 'Produkter lagda i varukorg'],
    ];

    $main_title = $titles[$metric][0];
    $donut_title = $titles[$metric][1];

    $total = gg_activity_daily_archive_get_total($event_type, $period_info);
    $series = gg_admin_analytics_get_activity_series($event_type, $period_info);
    $distribution = gg_admin_analytics_get_activity_distribution($event_type, $metric, $period_info, 10);

    $top_value = !empty($distribution[0]['value']) ? (int) $distribution[0]['value'] : 0;
    $last_event = '';

    foreach ($distribution as $item) {
        if (!empty($item['last_activity']) && (!$last_event || strtotime($item['last_activity']) > strtotime($last_event))) {
            $last_event = $item['last_activity'];
        }
    }

    $unique_sessions = 0;

    if (function_exists('gg_activity_table_exists') && gg_activity_table_exists()) {
        $table_name = $wpdb->prefix . 'gg_activity_log';

        $where = "WHERE event_type = %s AND session_key != ''";
        $params = [$event_type];

        if (!empty($period_info['start'])) {
            $where .= " AND created_at >= %s";
            $params[] = date_i18n('Y-m-d H:i:s', $period_info['start']);
        }

        $unique_sessions = (int) $wpdb->get_var(
            $wpdb->prepare(
                "SELECT COUNT(DISTINCT session_key)
                 FROM {$table_name}
                 {$where}",
                $params
            )
        );
    }

    $table_rows = [];

    foreach ($distribution as $item) {
        $table_rows[] = [
            'name'    => !empty($item['link'])
                ? '<a href="' . esc_url($item['link']) . '" target="_blank" rel="noopener noreferrer">' . esc_html($item['label']) . '</a>'
                : esc_html($item['label']),
            'value'   => (int) $item['value'],
            'share'   => $total > 0 ? round(((int) $item['value'] / $total) * 100) . '%' : '0%',
            'last'    => !empty($item['last_activity'])
                ? date_i18n('Y-m-d H:i', strtotime($item['last_activity']))
                : '—',
        ];
    }

    return [
        'generated_at'   => date_i18n('H:i:s', current_time('timestamp')),
        'period_label'   => $period_info['label'],
        'line_title'     => $main_title . ' över tid',
        'line_subtitle'  => $period_info['label'],
        'donut_title'    => $donut_title,
        'donut_subtitle' => 'Topplista från statistikarkivet',
        'table_title'    => $donut_title,
        'table_subtitle' => $period_info['label'],
        'kpis'           => [
            [
                'label'       => $main_title,
                'value'       => $total,
                'description' => $period_info['label'],
            ],
            [
                'label'       => 'Unika sessioner',
                'value'       => $unique_sessions,
                'description' => 'Från färsk aktivitetslogg',
            ],
            [
                'label'       => 'Största post',
                'value'       => $top_value,
                'description' => 'Högsta antal i fördelningen',
            ],
            [
                'label'       => 'Senaste aktivitet',
                'value'       => $last_event ? date_i18n('H:i', strtotime($last_event)) : '—',
                'description' => $last_event ? date_i18n('Y-m-d', strtotime($last_event)) : 'Ingen aktivitet',
            ],
        ],
        'series'         => $series,
        'segments'       => gg_admin_analytics_build_segments($distribution),
        'table'          => [
            'columns' => [
                ['key' => 'name', 'label' => $metric === 'page_views' ? 'Sida' : 'Produkt', 'html' => true],
                ['key' => 'value', 'label' => 'Antal', 'type' => 'number'],
                ['key' => 'share', 'label' => 'Andel', 'type' => 'number'],
                ['key' => 'last', 'label' => 'Senast'],
            ],
            'rows' => $table_rows,
        ],
    ];
}


function gg_admin_analytics_get_activity_series($event_type, $period_info) {
    if (!empty($period_info['key']) && $period_info['key'] === 'today') {
        return gg_admin_analytics_get_today_activity_series_from_log($event_type, $period_info);
    }

    if (!function_exists('gg_activity_daily_archive_get_series')) {
        return [];
    }

    $rows = gg_activity_daily_archive_get_series($event_type, $period_info);

    return gg_admin_analytics_normalize_series($rows, $period_info);
}


function gg_admin_analytics_get_today_activity_series_from_log($event_type, $period_info) {
    if (!function_exists('gg_activity_table_exists') || !gg_activity_table_exists()) {
        return gg_admin_analytics_normalize_series([], $period_info);
    }

    global $wpdb;

    $event_type = sanitize_key($event_type);

    if (!$event_type) {
        return gg_admin_analytics_normalize_series([], $period_info);
    }

    $table_name = $wpdb->prefix . 'gg_activity_log';

    $today_start = !empty($period_info['start'])
        ? (int) $period_info['start']
        : strtotime(date_i18n('Y-m-d 00:00:00', current_time('timestamp')));

    $rows = $wpdb->get_results(
        $wpdb->prepare(
            "SELECT
                DATE_FORMAT(created_at, '%%Y-%%m-%%d %%H:00:00') AS bucket,
                DATE_FORMAT(created_at, '%%H:00') AS label,
                COUNT(*) AS value
             FROM {$table_name}
             WHERE event_type = %s
             AND created_at >= %s
             GROUP BY bucket, label
             ORDER BY bucket ASC",
            $event_type,
            date_i18n('Y-m-d H:i:s', $today_start)
        ),
        ARRAY_A
    );

    return gg_admin_analytics_normalize_series($rows, $period_info);
}


function gg_admin_analytics_get_activity_distribution($event_type, $metric, $period_info, $limit = 10) {
    if (!function_exists('gg_activity_daily_archive_get_distribution')) {
        return [];
    }

    $rows = gg_activity_daily_archive_get_distribution($event_type, $period_info, $limit);
    $items = [];

    foreach ($rows as $row) {
        $label = !empty($row['label']) ? $row['label'] : $row['dimension_key'];

        $items[] = [
            'label'         => $label,
            'value'         => (int) $row['value'],
            'link'          => !empty($row['link']) ? $row['link'] : '',
            'last_activity' => !empty($row['last_activity']) ? $row['last_activity'] : '',
        ];
    }

    return $items;
}


		function gg_admin_analytics_normalize_series($rows, $period_info) {
    $map = [];

    foreach ($rows as $row) {
        if (empty($row['bucket'])) {
            continue;
        }

        $map[$row['bucket']] = [
            'label' => isset($row['label']) ? $row['label'] : $row['bucket'],
            'value' => isset($row['value']) ? (float) $row['value'] : 0,
        ];
    }

    if (!empty($period_info['key']) && $period_info['key'] === 'total') {
        return array_values($map);
    }

    $series = [];
    $now = current_time('timestamp');

    if (!empty($period_info['group']) && $period_info['group'] === 'hour') {
        $start = !empty($period_info['start'])
            ? (int) $period_info['start']
            : strtotime(date_i18n('Y-m-d 00:00:00', $now));

        for ($i = 0; $i < 24; $i++) {
            $timestamp = strtotime('+' . $i . ' hours', $start);
            $bucket = date_i18n('Y-m-d H:00:00', $timestamp);
            $label = date_i18n('H:00', $timestamp);

            $series[] = [
                'label' => $label,
                'value' => isset($map[$bucket]) ? (float) $map[$bucket]['value'] : 0,
            ];
        }

        return $series;
    }

    if (empty($period_info['start'])) {
        return array_values($map);
    }

    $start = (int) $period_info['start'];
    $days = max(1, floor(($now - $start) / DAY_IN_SECONDS) + 1);

    for ($i = 0; $i < $days; $i++) {
        $timestamp = strtotime('+' . $i . ' days', $start);
        $bucket = date_i18n('Y-m-d', $timestamp);
        $label = date_i18n('d/m', $timestamp);

        $series[] = [
            'label' => $label,
            'value' => isset($map[$bucket]) ? (float) $map[$bucket]['value'] : 0,
        ];
    }

    return $series;
}
			
function gg_admin_analytics_build_segments($items) {
    $segments = [];
    $shown_total = 0;
    $grand_total = 0;

    foreach ($items as $item) {
        $grand_total += (int) $item['value'];
    }

    foreach (array_slice($items, 0, 5) as $item) {
        $value = (int) $item['value'];
        $shown_total += $value;

        $segments[] = [
            'label' => $item['label'],
            'value' => $value,
        ];
    }

    $other = max(0, $grand_total - $shown_total);

    if ($other > 0) {
        $segments[] = [
            'label' => 'Övrigt',
            'value' => $other,
        ];
    }

    return $segments;
}


function gg_admin_analytics_get_sales_data($period) {
    $period_info = gg_admin_analytics_get_period_info($period);

    if (!class_exists('WooCommerce') || !function_exists('wc_get_orders')) {
        return gg_admin_analytics_empty_data('WooCommerce är inte aktivt.');
    }

    $args = [
        'limit'  => -1,
        'status' => ['processing', 'completed'],
        'return' => 'objects',
    ];

    if (!empty($period_info['start'])) {
        $args['date_created'] = '>=' . $period_info['start'];
    }

    $orders = wc_get_orders($args);

    $order_count = count($orders);
    $revenue = 0;
    $product_quantity = 0;
    $product_map = [];
    $series_map = [];

    foreach ($orders as $order) {
        $revenue += (float) $order->get_total();

        $created = $order->get_date_created();

        if ($created) {
            if ($period_info['group'] === 'hour') {
                $bucket = date_i18n('Y-m-d H:00:00', $created->getTimestamp());
                $label = date_i18n('H:00', $created->getTimestamp());
            } elseif ($period_info['group'] === 'month') {
                $bucket = date_i18n('Y-m-01', $created->getTimestamp());
                $label = date_i18n('Y-m', $created->getTimestamp());
            } else {
                $bucket = date_i18n('Y-m-d', $created->getTimestamp());
                $label = date_i18n('d/m', $created->getTimestamp());
            }

            if (!isset($series_map[$bucket])) {
                $series_map[$bucket] = [
                    'bucket' => $bucket,
                    'label'  => $label,
                    'value'  => 0,
                ];
            }

            $series_map[$bucket]['value'] += (float) $order->get_total();
        }

        foreach ($order->get_items() as $item) {
            $product_id = $item->get_product_id();
            $name = $item->get_name();
            $qty = (int) $item->get_quantity();
            $line_total = (float) $item->get_total();

            $product_quantity += $qty;

            if (!isset($product_map[$product_id])) {
                $product_map[$product_id] = [
                    'label'   => $name,
                    'value'   => 0,
                    'qty'     => 0,
                    'revenue' => 0,
                    'link'    => get_edit_post_link($product_id),
                ];
            }

            $product_map[$product_id]['value'] += $line_total;
            $product_map[$product_id]['qty'] += $qty;
            $product_map[$product_id]['revenue'] += $line_total;
        }
    }

    usort($product_map, function($a, $b) {
        return $b['revenue'] <=> $a['revenue'];
    });

    $series_rows = array_values($series_map);
    usort($series_rows, function($a, $b) {
        return strcmp($a['bucket'], $b['bucket']);
    });

    $series = gg_admin_analytics_normalize_series($series_rows, $period_info);

    $table_rows = [];

    foreach (array_slice($product_map, 0, 10) as $product) {
        $table_rows[] = [
            'name'    => $product['link']
                ? '<a href="' . esc_url($product['link']) . '">' . esc_html($product['label']) . '</a>'
                : esc_html($product['label']),
            'qty'     => (int) $product['qty'],
            'revenue' => wc_price($product['revenue']),
            'share'   => $revenue > 0 ? round(($product['revenue'] / $revenue) * 100) . '%' : '0%',
        ];
    }

    $segments = [];

    foreach (array_slice($product_map, 0, 6) as $product) {
        $segments[] = [
            'label' => $product['label'],
            'value' => round($product['revenue']),
        ];
    }

    return [
        'generated_at'   => date_i18n('H:i:s', current_time('timestamp')),
        'period_label'   => $period_info['label'],
        'line_title'     => 'Försäljning över tid',
        'line_subtitle'  => $period_info['label'],
        'donut_title'    => 'Försäljning per produkt',
        'donut_subtitle' => 'Baserat på omsättning',
        'table_title'    => 'Mest sålda produkter',
        'table_subtitle' => $period_info['label'],
        'kpis'           => [
            [
                'label'       => 'Omsättning',
                'value'       => wp_strip_all_tags(wc_price($revenue)),
                'description' => $period_info['label'],
            ],
            [
                'label'       => 'Ordrar',
                'value'       => $order_count,
                'description' => 'Betalda / behandlade',
            ],
            [
                'label'       => 'Produkter sålda',
                'value'       => $product_quantity,
                'description' => 'Antal orderrader',
            ],
            [
                'label'       => 'Snittorder',
                'value'       => $order_count > 0 ? wp_strip_all_tags(wc_price($revenue / $order_count)) : '0 kr',
                'description' => 'Omsättning / order',
            ],
        ],
        'series'         => $series,
        'segments'       => $segments,
        'table'          => [
            'columns' => [
                ['key' => 'name', 'label' => 'Produkt', 'html' => true],
                ['key' => 'qty', 'label' => 'Antal', 'type' => 'number'],
                ['key' => 'revenue', 'label' => 'Omsättning', 'type' => 'number', 'html' => true],
                ['key' => 'share', 'label' => 'Andel', 'type' => 'number'],
            ],
            'rows' => $table_rows,
        ],
    ];
}


function gg_admin_analytics_empty_data($message) {
    return [
        'generated_at'   => date_i18n('H:i:s', current_time('timestamp')),
        'period_label'   => '',
        'line_title'     => 'Ingen data',
        'line_subtitle'  => '',
        'donut_title'    => 'Ingen data',
        'donut_subtitle' => '',
        'table_title'    => 'Ingen data',
        'table_subtitle' => '',
        'kpis'           => [
            ['label' => 'Status', 'value' => '—', 'description' => $message],
            ['label' => 'Data', 'value' => '0', 'description' => 'Ingen data'],
            ['label' => 'Period', 'value' => '—', 'description' => 'Ingen data'],
            ['label' => 'Senast', 'value' => '—', 'description' => 'Ingen data'],
        ],
        'series'         => [],
        'segments'       => [],
        'table'          => [
            'columns' => [],
            'rows'    => [],
        ],
    ];
}

/**
 * Gold Goblins Dagligt Statistikarkiv
 */
/**
 * Gold Goblins Dagligt Statistikarkiv
 */

add_action('init', 'gg_activity_daily_archive_install_table', 8);
add_action('init', 'gg_activity_daily_archive_process_log_rows', 40);
add_action('gg_activity_cleanup_daily', 'gg_activity_daily_archive_process_log_rows', 1);

function gg_activity_daily_archive_install_table() {
    global $wpdb;

    $version = '1.0.0';

    if (get_option('gg_activity_daily_archive_db_version') === $version) {
        return;
    }

    require_once ABSPATH . 'wp-admin/includes/upgrade.php';

    $table_name = $wpdb->prefix . 'gg_activity_daily_stats';
    $charset_collate = $wpdb->get_charset_collate();

    $sql = "CREATE TABLE {$table_name} (
        id bigint(20) unsigned NOT NULL AUTO_INCREMENT,
        stat_date date NOT NULL,
        metric_key varchar(80) NOT NULL,
        dimension_type varchar(80) NOT NULL DEFAULT '',
        dimension_key varchar(500) NOT NULL DEFAULT '',
        dimension_hash char(32) NOT NULL,
        dimension_label varchar(255) NOT NULL DEFAULT '',
        dimension_link varchar(500) NOT NULL DEFAULT '',
        count_value bigint(20) unsigned NOT NULL DEFAULT 0,
        last_activity datetime NOT NULL,
        updated_at datetime NOT NULL,
        PRIMARY KEY  (id),
        UNIQUE KEY stat_metric_dimension (stat_date, metric_key, dimension_hash),
        KEY metric_date (metric_key, stat_date),
        KEY dimension_lookup (metric_key, dimension_hash)
    ) {$charset_collate};";

    dbDelta($sql);

    update_option('gg_activity_daily_archive_db_version', $version, false);
}


function gg_activity_daily_archive_table_exists() {
    global $wpdb;

    $table_name = $wpdb->prefix . 'gg_activity_daily_stats';

    return $wpdb->get_var(
        $wpdb->prepare(
            'SHOW TABLES LIKE %s',
            $table_name
        )
    ) === $table_name;
}


function gg_activity_daily_archive_process_log_rows($limit = 3000) {
    global $wpdb;

    $activity_table = $wpdb->prefix . 'gg_activity_log';
    $archive_table = $wpdb->prefix . 'gg_activity_daily_stats';

    if (
        !function_exists('gg_activity_table_exists') ||
        !gg_activity_table_exists() ||
        !gg_activity_daily_archive_table_exists()
    ) {
        return;
    }

    $limit = max(100, min(5000, absint($limit)));
    $last_id = absint(get_option('gg_activity_daily_archive_last_log_id', 0));

    $rows = $wpdb->get_results(
        $wpdb->prepare(
            "SELECT id, event_type, event_label, object_id, object_type, page_url, created_at
             FROM {$activity_table}
             WHERE id > %d
             ORDER BY id ASC
             LIMIT %d",
            $last_id,
            $limit
        )
    );

    if (empty($rows)) {
        return;
    }

    $max_id = $last_id;

    foreach ($rows as $row) {
        $metric_key = sanitize_key($row->event_type);

        if (!$metric_key) {
            continue;
        }

        $dimension = gg_activity_daily_archive_get_dimension($row);

        if (empty($dimension['key'])) {
            continue;
        }

        $stat_date = date_i18n('Y-m-d', strtotime($row->created_at));
        $dimension_hash = md5($metric_key . '|' . $dimension['type'] . '|' . $dimension['key']);

        $wpdb->query(
            $wpdb->prepare(
                "INSERT INTO {$archive_table}
                    (stat_date, metric_key, dimension_type, dimension_key, dimension_hash, dimension_label, dimension_link, count_value, last_activity, updated_at)
                 VALUES
                    (%s, %s, %s, %s, %s, %s, %s, 1, %s, %s)
                 ON DUPLICATE KEY UPDATE
                    count_value = count_value + 1,
                    dimension_label = VALUES(dimension_label),
                    dimension_link = VALUES(dimension_link),
                    last_activity = GREATEST(last_activity, VALUES(last_activity)),
                    updated_at = VALUES(updated_at)",
                $stat_date,
                $metric_key,
                $dimension['type'],
                $dimension['key'],
                $dimension_hash,
                $dimension['label'],
                $dimension['link'],
                $row->created_at,
                current_time('mysql')
            )
        );

        $max_id = max($max_id, absint($row->id));
    }

    update_option('gg_activity_daily_archive_last_log_id', $max_id, false);
    update_option('gg_activity_daily_archive_last_run', current_time('mysql'), false);

    if (count($rows) === $limit) {
        gg_activity_daily_archive_process_log_rows($limit);
    }
}


function gg_activity_daily_archive_get_dimension($row) {
    $event_type = sanitize_key($row->event_type);
    $object_id = absint($row->object_id);
    $object_type = sanitize_key($row->object_type);
    $label = sanitize_text_field($row->event_label);
    $page_url = esc_url_raw($row->page_url);

    if ($event_type === 'page_view') {
        $path = '/';

        if ($page_url) {
            $parsed_path = wp_parse_url($page_url, PHP_URL_PATH);

            if ($parsed_path) {
                $path = untrailingslashit($parsed_path);

                if ($path === '') {
                    $path = '/';
                }
            }
        }

        return [
            'type'  => 'page',
            'key'   => $path,
            'label' => $label ? $label : $path,
            'link'  => $page_url,
        ];
    }

    if (
        in_array($event_type, ['product_view', 'add_to_cart', 'product_gallery_click', 'info_panel_open'], true) &&
        $object_type === 'product' &&
        $object_id > 0
    ) {
        $product_title = get_the_title($object_id);

        return [
            'type'  => 'product',
            'key'   => (string) $object_id,
            'label' => $product_title ? $product_title : ($label ? $label : 'Produkt #' . $object_id),
            'link'  => get_permalink($object_id),
        ];
    }

    return [
        'type'  => $object_type ? $object_type : 'event',
        'key'   => $object_id ? (string) $object_id : $event_type,
        'label' => $label ? $label : $event_type,
        'link'  => $page_url,
    ];
}


function gg_activity_daily_archive_get_total($metric_key, $period_info = []) {
    gg_activity_daily_archive_process_log_rows();

    if (!gg_activity_daily_archive_table_exists()) {
        return 0;
    }

    global $wpdb;

    $metric_key = sanitize_key($metric_key);
    $table_name = $wpdb->prefix . 'gg_activity_daily_stats';

    $sql = "SELECT SUM(count_value)
            FROM {$table_name}
            WHERE metric_key = %s";

    $params = [$metric_key];

    if (!empty($period_info['start'])) {
        $sql .= " AND stat_date >= %s";
        $params[] = date_i18n('Y-m-d', $period_info['start']);
    }

    return (int) $wpdb->get_var(
        $wpdb->prepare($sql, $params)
    );
}


function gg_activity_daily_archive_get_series($metric_key, $period_info) {
    gg_activity_daily_archive_process_log_rows();

    if (!gg_activity_daily_archive_table_exists()) {
        return [];
    }

    global $wpdb;

    $metric_key = sanitize_key($metric_key);
    $table_name = $wpdb->prefix . 'gg_activity_daily_stats';

    $params = [$metric_key];

    if (!empty($period_info['start'])) {
        $where = "WHERE metric_key = %s AND stat_date >= %s";
        $params[] = date_i18n('Y-m-d', $period_info['start']);
    } else {
        $where = "WHERE metric_key = %s";
    }

    if (!empty($period_info['key']) && $period_info['key'] === 'total') {
        return $wpdb->get_results(
            $wpdb->prepare(
                "SELECT
                    DATE_FORMAT(stat_date, '%%Y-%%m-01') AS bucket,
                    DATE_FORMAT(stat_date, '%%Y-%%m') AS label,
                    SUM(count_value) AS value
                 FROM {$table_name}
                 {$where}
                 GROUP BY bucket, label
                 ORDER BY bucket ASC",
                $params
            ),
            ARRAY_A
        );
    }

    return $wpdb->get_results(
        $wpdb->prepare(
            "SELECT
                stat_date AS bucket,
                DATE_FORMAT(stat_date, '%%d/%%m') AS label,
                SUM(count_value) AS value
             FROM {$table_name}
             {$where}
             GROUP BY stat_date
             ORDER BY stat_date ASC",
            $params
        ),
        ARRAY_A
    );
}


function gg_activity_daily_archive_get_distribution($metric_key, $period_info, $limit = 10) {
    gg_activity_daily_archive_process_log_rows();

    if (!gg_activity_daily_archive_table_exists()) {
        return [];
    }

    global $wpdb;

    $metric_key = sanitize_key($metric_key);
    $limit = max(1, min(50, absint($limit)));
    $table_name = $wpdb->prefix . 'gg_activity_daily_stats';

    $params = [$metric_key];

    if (!empty($period_info['start'])) {
        $where = "WHERE metric_key = %s AND stat_date >= %s";
        $params[] = date_i18n('Y-m-d', $period_info['start']);
    } else {
        $where = "WHERE metric_key = %s";
    }

    $params[] = $limit;

    return $wpdb->get_results(
        $wpdb->prepare(
            "SELECT
                dimension_type,
                dimension_key,
                MAX(dimension_label) AS label,
                MAX(dimension_link) AS link,
                SUM(count_value) AS value,
                MAX(last_activity) AS last_activity
             FROM {$table_name}
             {$where}
             GROUP BY dimension_type, dimension_key
             ORDER BY value DESC
             LIMIT %d",
            $params
        ),
        ARRAY_A
    );
}


add_action('admin_menu', 'gg_activity_daily_archive_register_admin_page', 47);

function gg_activity_daily_archive_register_admin_page() {
    add_submenu_page(
        'gg-admin-overview',
        'Statistikarkiv',
        'Statistikarkiv',
        'manage_options',
        'gg-activity-daily-archive',
        'gg_activity_daily_archive_render_admin_page'
    );
}


function gg_activity_daily_archive_render_admin_page() {
    if (!current_user_can('manage_options')) {
        wp_die('Du har inte behörighet att visa denna sida.');
    }

    if (
        isset($_POST['gg_daily_archive_process']) &&
        check_admin_referer('gg_daily_archive_manual_process', 'gg_daily_archive_nonce')
    ) {
        gg_activity_daily_archive_process_log_rows(5000);

        echo '<div class="notice notice-success is-dismissible"><p>Statistikarkivet har uppdaterats.</p></div>';
    }

    global $wpdb;

    $table_name = $wpdb->prefix . 'gg_activity_daily_stats';
    $rows_count = gg_activity_daily_archive_table_exists()
        ? (int) $wpdb->get_var("SELECT COUNT(*) FROM {$table_name}")
        : 0;

    $last_log_id = absint(get_option('gg_activity_daily_archive_last_log_id', 0));
    $last_run = get_option('gg_activity_daily_archive_last_run');
    ?>

    <div class="wrap">
        <h1>Gold Goblins Statistikarkiv</h1>

        <p>
            Här sparas summerad statistik per dag, sida och produkt. Den här datan kan ligga kvar även om detaljerad aktivitetslogg rensas.
        </p>

        <table class="widefat striped" style="max-width:760px;">
            <tbody>
                <tr>
                    <th>Arkivrader</th>
                    <td><?php echo esc_html($rows_count); ?></td>
                </tr>

                <tr>
                    <th>Senast behandlad aktivitetsrad</th>
                    <td><?php echo esc_html($last_log_id); ?></td>
                </tr>

                <tr>
                    <th>Senast uppdaterad</th>
                    <td><?php echo $last_run ? esc_html(date_i18n('Y-m-d H:i', strtotime($last_run))) : 'Inte körd ännu'; ?></td>
                </tr>
            </tbody>
        </table>

        <form method="post" style="margin-top:18px;">
            <?php wp_nonce_field('gg_daily_archive_manual_process', 'gg_daily_archive_nonce'); ?>

            <button type="submit" name="gg_daily_archive_process" value="1" class="button button-primary">
                Uppdatera statistikarkiv nu
            </button>
        </form>
    </div>

    <?php
}
