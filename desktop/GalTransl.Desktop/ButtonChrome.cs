using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;

namespace GalTransl.Desktop;

public static class ButtonChrome {
    // Keep native dark buttons readable on hover and when disabled instead of
    // falling back to the system's pale-blue/white WPF theme.
    public static void Apply(Button button){
        var border=new FrameworkElementFactory(typeof(Border),"Chrome");
        border.SetValue(Border.BackgroundProperty,new TemplateBindingExtension(Control.BackgroundProperty));
        border.SetValue(Border.BorderBrushProperty,new TemplateBindingExtension(Control.BorderBrushProperty));
        border.SetValue(Border.BorderThicknessProperty,new TemplateBindingExtension(Control.BorderThicknessProperty));
        border.SetValue(Border.PaddingProperty,new TemplateBindingExtension(Control.PaddingProperty));
        border.SetValue(Border.CornerRadiusProperty,new CornerRadius(8));
        var content=new FrameworkElementFactory(typeof(ContentPresenter));
        content.SetValue(ContentPresenter.HorizontalAlignmentProperty,HorizontalAlignment.Center);
        content.SetValue(ContentPresenter.VerticalAlignmentProperty,VerticalAlignment.Center);
        content.SetValue(ContentPresenter.RecognizesAccessKeyProperty,true);border.AppendChild(content);
        var template=new ControlTemplate(typeof(Button)){VisualTree=border};
        var hover=new Trigger{Property=UIElement.IsMouseOverProperty,Value=true};
        hover.Setters.Add(new Setter(Border.BorderBrushProperty,VisualTheme.Brush(VisualTheme.Ink,.35),"Chrome"));template.Triggers.Add(hover);
        var focus=new Trigger{Property=UIElement.IsKeyboardFocusedProperty,Value=true};
        focus.Setters.Add(new Setter(Border.BorderBrushProperty,VisualTheme.Brush(VisualTheme.Ink,.7),"Chrome"));template.Triggers.Add(focus);
        var disabled=new Trigger{Property=UIElement.IsEnabledProperty,Value=false};
        disabled.Setters.Add(new Setter(Border.BackgroundProperty,VisualTheme.Brush(VisualTheme.Surface,.3),"Chrome"));
        disabled.Setters.Add(new Setter(UIElement.OpacityProperty,.7,"Chrome"));template.Triggers.Add(disabled);
        button.Background=VisualTheme.Brush(VisualTheme.Surface);button.Foreground=VisualTheme.Brush(VisualTheme.Ink);
        button.BorderBrush=VisualTheme.Brush(VisualTheme.Surface);button.BorderThickness=new Thickness(1);button.Template=template;
    }
}
