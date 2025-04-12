# client/get_api_key_gui.py
import sys
import dearpygui.dearpygui as dpg
import os  # Keep os import if needed elsewhere, otherwise remove

def get_api_key():
    api_key_ref = [None]  # Use a list to pass the key out of the callback

    def submit_callback(sender, app_data, user_data):
        api_key_ref[0] = dpg.get_value("api_key_input")
        dpg.stop_dearpygui()

    dpg.create_context()
    # Set a fixed viewport height again, slightly larger than before
    dpg.create_viewport(title='API Key Required', width=400, height=160, max_height=160, always_on_top=True)
    dpg.setup_dearpygui()

    # Create and bind the dark theme globally
    with dpg.theme() as global_theme:
        with dpg.theme_component(dpg.mvAll):  # Apply to all item types
            # Style Adjustments
            dpg.add_theme_style(dpg.mvStyleVar_WindowPadding, 8, 8, category=dpg.mvThemeCat_Core)
            dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 4, 3, category=dpg.mvThemeCat_Core)
            dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, 8, 4, category=dpg.mvThemeCat_Core)
            dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 3, category=dpg.mvThemeCat_Core)  # Add some rounding

            # Color Adjustments (Dark Theme Example)
            dpg.add_theme_color(dpg.mvThemeCol_WindowBg, (37, 37, 38), category=dpg.mvThemeCat_Core)
            dpg.add_theme_color(dpg.mvThemeCol_ChildBg, (28, 28, 28), category=dpg.mvThemeCat_Core)
            dpg.add_theme_color(dpg.mvThemeCol_PopupBg, (45, 45, 45), category=dpg.mvThemeCat_Core)
            dpg.add_theme_color(dpg.mvThemeCol_Border, (70, 70, 70), category=dpg.mvThemeCat_Core)
            dpg.add_theme_color(dpg.mvThemeCol_FrameBg, (54, 54, 54), category=dpg.mvThemeCat_Core)
            dpg.add_theme_color(dpg.mvThemeCol_FrameBgHovered, (69, 69, 69), category=dpg.mvThemeCat_Core)
            dpg.add_theme_color(dpg.mvThemeCol_FrameBgActive, (84, 84, 84), category=dpg.mvThemeCat_Core)
            dpg.add_theme_color(dpg.mvThemeCol_TitleBg, (30, 30, 30), category=dpg.mvThemeCat_Core)
            dpg.add_theme_color(dpg.mvThemeCol_TitleBgActive, (45, 45, 45), category=dpg.mvThemeCat_Core)
            dpg.add_theme_color(dpg.mvThemeCol_TitleBgCollapsed, (30, 30, 30), category=dpg.mvThemeCat_Core)
            dpg.add_theme_color(dpg.mvThemeCol_MenuBarBg, (45, 45, 45), category=dpg.mvThemeCat_Core)
            dpg.add_theme_color(dpg.mvThemeCol_ScrollbarBg, (30, 30, 30), category=dpg.mvThemeCat_Core)
            dpg.add_theme_color(dpg.mvThemeCol_ScrollbarGrab, (80, 80, 80), category=dpg.mvThemeCat_Core)
            dpg.add_theme_color(dpg.mvThemeCol_ScrollbarGrabHovered, (100, 100, 100), category=dpg.mvThemeCat_Core)
            dpg.add_theme_color(dpg.mvThemeCol_ScrollbarGrabActive, (120, 120, 120), category=dpg.mvThemeCat_Core)
            dpg.add_theme_color(dpg.mvThemeCol_CheckMark, (230, 230, 230), category=dpg.mvThemeCat_Core)
            dpg.add_theme_color(dpg.mvThemeCol_SliderGrab, (80, 80, 80), category=dpg.mvThemeCat_Core)
            dpg.add_theme_color(dpg.mvThemeCol_SliderGrabActive, (120, 120, 120), category=dpg.mvThemeCat_Core)
            dpg.add_theme_color(dpg.mvThemeCol_Button, (69, 69, 69), category=dpg.mvThemeCat_Core)
            dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (84, 84, 84), category=dpg.mvThemeCat_Core)
            dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, (100, 100, 100), category=dpg.mvThemeCat_Core)
            dpg.add_theme_color(dpg.mvThemeCol_Header, (69, 69, 69), category=dpg.mvThemeCat_Core)
            dpg.add_theme_color(dpg.mvThemeCol_HeaderHovered, (84, 84, 84), category=dpg.mvThemeCat_Core)
            dpg.add_theme_color(dpg.mvThemeCol_HeaderActive, (100, 100, 100), category=dpg.mvThemeCat_Core)
            dpg.add_theme_color(dpg.mvThemeCol_Separator, (70, 70, 70), category=dpg.mvThemeCat_Core)
            dpg.add_theme_color(dpg.mvThemeCol_SeparatorHovered, (100, 100, 100), category=dpg.mvThemeCat_Core)
            dpg.add_theme_color(dpg.mvThemeCol_SeparatorActive, (120, 120, 120), category=dpg.mvThemeCat_Core)
            dpg.add_theme_color(dpg.mvThemeCol_ResizeGrip, (80, 80, 80), category=dpg.mvThemeCat_Core)
            dpg.add_theme_color(dpg.mvThemeCol_ResizeGripHovered, (100, 100, 100), category=dpg.mvThemeCat_Core)
            dpg.add_theme_color(dpg.mvThemeCol_ResizeGripActive, (120, 120, 120), category=dpg.mvThemeCat_Core)
            dpg.add_theme_color(dpg.mvThemeCol_Tab, (54, 54, 54), category=dpg.mvThemeCat_Core)
            dpg.add_theme_color(dpg.mvThemeCol_TabHovered, (84, 84, 84), category=dpg.mvThemeCat_Core)
            dpg.add_theme_color(dpg.mvThemeCol_TabActive, (69, 69, 69), category=dpg.mvThemeCat_Core)
            dpg.add_theme_color(dpg.mvThemeCol_TabUnfocused, (54, 54, 54), category=dpg.mvThemeCat_Core)
            dpg.add_theme_color(dpg.mvThemeCol_TabUnfocusedActive, (69, 69, 69), category=dpg.mvThemeCat_Core)
            dpg.add_theme_color(dpg.mvThemeCol_Text, (230, 230, 230), category=dpg.mvThemeCat_Core)
            dpg.add_theme_color(dpg.mvThemeCol_TextDisabled, (128, 128, 128), category=dpg.mvThemeCat_Core)
            dpg.add_theme_color(dpg.mvThemeCol_NavHighlight, (84, 84, 84), category=dpg.mvThemeCat_Core)  # Navigation highlight (e.g., keyboard focus)

    dpg.bind_theme(global_theme)  # Bind the theme

    # Use fixed height matching the viewport, remove autosize
    with dpg.window(label="API Key Input", width=400, height=160, no_close=True, no_move=True, no_resize=True):
        dpg.add_text("Please enter your API key:")
        dpg.add_input_text(label="", tag="api_key_input", password=True, width=-1)
        dpg.add_spacer(height=10)
        dpg.add_button(label="Submit", callback=submit_callback, width=-1)

    dpg.show_viewport()
    dpg.start_dearpygui()
    dpg.destroy_context()

    return api_key_ref[0]

if __name__ == "__main__":
    key = get_api_key()
    if key:
        print(key)
        sys.exit(0)
    else:
        # Dear PyGui doesn't easily distinguish between cancel and empty submit in this simple setup
        # It will return None if the window is closed before submitting, or an empty string if submitted empty.
        print("API key dialog closed or no key entered.", file=sys.stderr)
        sys.exit(1)
